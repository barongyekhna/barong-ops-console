<?php
/**
 * Plugin Name: Barong Perf
 * Description: 前台脚本减负(瘦插件)。按页面类型卸掉确定用不到的脚本:密码强度三件套只留账户/结账页、WooPayments 遥测全卸、Google 登录按钮只留账户页、Jetpack 相关文章不进商店页。只做 dequeue,不改任何插件行为;列表经 REST 可查(?by-pf-ping)。
 * Version: 1.0.0
 * Author: Barong Yekhna Console
 */

if ( ! defined( 'ABSPATH' ) ) { exit; }

const BY_PF_VERSION = '1.0.0';

/** 计算本次请求要卸载的 handle 列表(纯函数,便于诊断口回显)。 */
function by_pf_removals() {
	$removals = array();

	$is_account_or_checkout = (
		( function_exists( 'is_account_page' ) && is_account_page() ) ||
		( function_exists( 'is_checkout' ) && is_checkout() )
	);
	if ( ! $is_account_or_checkout ) {
		// 密码强度三件套:只有注册/改密表单需要
		$removals[] = 'password-strength-meter';
		$removals[] = 'wc-password-strength-meter';
		$removals[] = 'zxcvbn-async';
		// Google 登录按钮只出现在账户页的登录表单
		$removals[] = 'googlesitekit-sign-in-with-google';
	}

	// WooPayments 前台遥测:纯上报,买家无感
	$removals[] = 'wcpay-frontend-tracks';
	$removals[] = 'woocommerce-payments-frontend-tracks';

	// Jetpack 相关文章:商店场景无用(博客文章保留)
	if ( function_exists( 'is_woocommerce' ) && function_exists( 'is_cart' ) && function_exists( 'is_checkout' )
		&& ( is_woocommerce() || is_cart() || is_checkout() ) ) {
		$removals[] = 'jetpack_related-posts';
	}

	return $removals;
}

add_action( 'wp_enqueue_scripts', function () {
	if ( is_admin() ) { return; }
	foreach ( by_pf_removals() as $handle ) {
		wp_dequeue_script( $handle );
		wp_dequeue_style( $handle );
	}
}, 9999 );

/** 诊断:当前页会卸掉什么(密钥保护,与 CS 共用 barong_cs_key)。 */
add_action( 'template_redirect', function () {
	if ( ! isset( $_GET['by-pf-ping'] ) ) { return; }
	$secret = (string) get_option( 'barong_cs_key', '' );
	$given  = sanitize_text_field( wp_unslash( $_GET['by-pf-ping'] ) );
	header( 'Content-Type: application/json; charset=UTF-8' );
	if ( '' === $secret || ! hash_equals( $secret, $given ) ) {
		echo wp_json_encode( array( 'ok' => false ) );
		exit;
	}
	echo wp_json_encode( array(
		'ok'       => true,
		'version'  => BY_PF_VERSION,
		'removals' => by_pf_removals(),
	) );
	exit;
}, 0 );
