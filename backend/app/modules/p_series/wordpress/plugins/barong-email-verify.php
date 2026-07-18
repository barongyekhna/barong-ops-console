<?php
/**
 * Plugin Name: Barong Email Verify
 * Description: 注册邮箱验证(瘦插件)。新注册用户必须点击邮件里的验证链接才能登录——不存在的邮箱收不到信,自然无法激活。旧用户与 Google 登录用户不受影响。
 * Version: 1.5.0
 * Author: Barong Yekhna Console
 */

if ( ! defined( 'ABSPATH' ) ) { exit; }

const BY_EV_META_TOKEN    = '_by_verify_token';
const BY_EV_META_VERIFIED = '_by_email_verified';
const BY_EV_VERSION       = '1.5.0';


/** 注册后:不自动登录,发验证邮件。 */
add_filter( 'woocommerce_registration_auth_new_customer', '__return_false' );

add_action( 'woocommerce_created_customer', function ( $customer_id ) {
	$user = get_user_by( 'id', $customer_id );
	if ( ! $user ) { return; }
	$token = wp_generate_password( 40, false, false );
	update_user_meta( $customer_id, BY_EV_META_TOKEN, $token );
	update_user_meta( $customer_id, BY_EV_META_VERIFIED, '0' );
	by_ev_send_mail( $user, $token );
}, 10, 1 );

function by_ev_build_body( $link, $logo_src = null ) {
	$logo = $logo_src ? $logo_src : home_url( '/wp-content/uploads/2026/07/byhome-phoenix-hero-v5-poster.jpg' );
	$body = '<div style="font-family:-apple-system,system-ui,Segoe UI,sans-serif;max-width:520px;width:100%;box-sizing:border-box;margin:0 auto;padding:28px 22px;color:#1b1a18">'
		. '<p style="text-align:center;margin:0 0 20px"><img src="' . esc_url( $logo ) . '" alt="Barong Yekhna" width="200" style="width:200px;max-width:70%;height:auto;border-radius:14px;display:inline-block"></p>'
		. '<h2 style="letter-spacing:-0.01em;text-align:center;margin:0 0 14px">Confirm your email address</h2>'
		. '<p style="text-align:center;color:#3d3a36">Thanks for creating an account at <strong>Barong Yekhna</strong>. Click the button below to verify your email and activate your account.</p>'
		. '<p style="margin:26px 0;text-align:center"><a href="' . esc_url( $link ) . '" style="background:#1b1a18;color:#faf9f6;text-decoration:none;padding:13px 26px;border-radius:999px;display:inline-block">Verify my email</a></p>'
		. '<p style="color:#6f6b66;font-size:13px;word-break:break-all;overflow-wrap:anywhere">If the button does not work, copy this link into your browser:<br>' . esc_url( $link ) . '</p>'
		. '<p style="color:#6f6b66;font-size:13px">If you did not create this account, you can safely ignore this email.</p>'
		. '</div>';
	return $body;
}

function by_ev_send_mail( $user, $token ) {
	$link    = add_query_arg(
		array( 'by-verify' => rawurlencode( $token ), 'uid' => (int) $user->ID ),
		home_url( '/' )
	);
	$subject = 'Verify your email — Barong Yekhna';
	$body    = by_ev_build_body( $link, 'cid:byphoenix' );
	$GLOBALS['by_ev_embed_logo'] = true;
	$from    = get_option( 'woocommerce_email_from_address', 'service@' . wp_parse_url( home_url(), PHP_URL_HOST ) );
	$headers = array(
		'Content-Type: text/html; charset=UTF-8',
		'From: Barong Yekhna (no reply) <' . $from . '>',
	);
	wp_mail( $user->user_email, $subject, $body, $headers );
}

/** 发验证信时把凤凰 logo 内嵌进邮件本体(cid),不依赖客户端加载外链图。 */
add_action( 'phpmailer_init', function ( $phpmailer ) {
	if ( empty( $GLOBALS['by_ev_embed_logo'] ) ) { return; }
	unset( $GLOBALS['by_ev_embed_logo'] );
	$uploads = wp_upload_dir();
	$path    = trailingslashit( $uploads['basedir'] ) . '2026/07/byhome-phoenix-hero-v5-poster.jpg';
	if ( file_exists( $path ) ) {
		try {
			$phpmailer->addEmbeddedImage( $path, 'byphoenix', 'barong-yekhna.jpg' );
		} catch ( Exception $e ) {}
	}
} );

/** 出站邮件窃听(诊断用):记录每封经 wp_mail 离站的信的指纹。 */
add_filter( 'wp_mail', function ( $atts ) {
	$log   = get_option( 'by_ev_maillog', array() );
	$body  = isset( $atts['message'] ) ? (string) $atts['message'] : '';
	$log[] = array(
		'time'     => gmdate( 'c' ),
		'to'       => isset( $atts['to'] ) ? ( is_array( $atts['to'] ) ? implode( ',', $atts['to'] ) : (string) $atts['to'] ) : '',
		'subject'  => isset( $atts['subject'] ) ? (string) $atts['subject'] : '',
		'len'      => strlen( $body ),
		'has_logo' => ( false !== strpos( $body, 'byhome-phoenix-hero-v5-poster' ) ),
		'head120'  => substr( wp_strip_all_tags( $body ), 0, 120 ),
	);
	update_option( 'by_ev_maillog', array_slice( $log, -10 ), false );
	return $atts;
}, PHP_INT_MAX );

/** 验证链接处理 + 重发。 */
add_action( 'template_redirect', function () {
	if ( isset( $_GET['by-ev-ping'] ) ) {
		header( 'Content-Type: text/plain' );
		echo 'barong-email-verify running version: ' . BY_EV_VERSION;
		exit;
	}
	if ( isset( $_GET['by-ev-maillog'] ) ) {
		header( 'Content-Type: application/json' );
		echo wp_json_encode( get_option( 'by_ev_maillog', array() ) );
		exit;
	}
	if ( isset( $_GET['by-ev-preview'] ) ) {
		header( 'Content-Type: text/html; charset=UTF-8' );
		echo '<!doctype html><meta name="robots" content="noindex">';
		echo by_ev_build_body( home_url( '/?by-verify=PREVIEW&uid=0' ) );
		exit;
	}
	if ( isset( $_GET['by-verify'], $_GET['uid'] ) ) {
		$uid   = (int) $_GET['uid'];
		$token = sanitize_text_field( wp_unslash( $_GET['by-verify'] ) );
		$saved = get_user_meta( $uid, BY_EV_META_TOKEN, true );
		$account = wc_get_page_permalink( 'myaccount' );
		if ( $saved && hash_equals( $saved, $token ) ) {
			update_user_meta( $uid, BY_EV_META_VERIFIED, '1' );
			delete_user_meta( $uid, BY_EV_META_TOKEN );
			if ( function_exists( 'wc_add_notice' ) ) {
				wc_add_notice( 'Your email is verified — you can now log in. Welcome to Barong Yekhna!', 'success' );
			}
		} elseif ( function_exists( 'wc_add_notice' ) ) {
			wc_add_notice( 'This verification link is invalid or has already been used. Try logging in, or register again.', 'error' );
		}
		wp_safe_redirect( $account ? $account : home_url( '/' ) );
		exit;
	}
	if ( isset( $_GET['by-resend'], $_GET['k'] ) ) {
		$uid   = (int) $_GET['by-resend'];
		$key   = sanitize_text_field( wp_unslash( $_GET['k'] ) );
		$saved = get_user_meta( $uid, BY_EV_META_TOKEN, true );
		$account = wc_get_page_permalink( 'myaccount' );
		if ( $saved && hash_equals( md5( $saved ), $key ) && ! get_transient( 'by_ev_rs_' . $uid ) ) {
			set_transient( 'by_ev_rs_' . $uid, 1, 5 * MINUTE_IN_SECONDS );
			$user = get_user_by( 'id', $uid );
			if ( $user ) { by_ev_send_mail( $user, $saved ); }
			if ( function_exists( 'wc_add_notice' ) ) {
				wc_add_notice( 'Verification email sent again — please check your inbox and spam folder.', 'success' );
			}
		} elseif ( function_exists( 'wc_add_notice' ) ) {
			wc_add_notice( 'Please wait a few minutes before requesting another email.', 'notice' );
		}
		wp_safe_redirect( $account ? $account : home_url( '/' ) );
		exit;
	}
} );

/** 未验证禁止登录(仅拦"有待验证标记"的新注册;旧用户/Google 登录不受影响)。 */
add_filter( 'wp_authenticate_user', function ( $user ) {
	if ( is_wp_error( $user ) || ! $user instanceof WP_User ) { return $user; }
	if ( user_can( $user, 'manage_options' ) || user_can( $user, 'manage_woocommerce' ) ) { return $user; }
	$token = get_user_meta( $user->ID, BY_EV_META_TOKEN, true );
	$state = get_user_meta( $user->ID, BY_EV_META_VERIFIED, true );
	if ( $token && '1' !== $state ) {
		$resend = add_query_arg(
			array( 'by-resend' => (int) $user->ID, 'k' => md5( $token ) ),
			home_url( '/' )
		);
		return new WP_Error(
			'by_email_not_verified',
			'Please verify your email address first — we sent a confirmation link to your inbox (check spam too). '
			. '<a href="' . esc_url( $resend ) . '">Resend verification email</a>.'
		);
	}
	return $user;
}, 20 );
