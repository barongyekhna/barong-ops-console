<?php
/**
 * Plugin Name: Barong Perf
 * Description: 前台脚本减负(瘦插件)。只卸真正无买家价值的脚本:WooPayments 前台遥测(早晚两道岗,防渲染中途入队)、Jetpack 相关文章不进商店页。登录弹窗相关组件(密码强度/Google 登录)保留——Flatsome 全站渲染登录弹窗,它们是在岗的。诊断:?by-pf-ping=<key>。
 * Version: 1.1.0
 * Author: Barong Yekhna Console
 */

if ( ! defined( 'ABSPATH' ) ) { exit; }

const BY_PF_VERSION = '1.1.0';

/** 遥测类:任何页面都不该让买家下载。 */
function by_pf_telemetry_handles() {
	return array( 'wcpay-frontend-tracks', 'woocommerce-payments-frontend-tracks' );
}

/** 早班岗:常规入队时机的卸载。 */
add_action( 'wp_enqueue_scripts', function () {
	if ( is_admin() ) { return; }
	foreach ( by_pf_telemetry_handles() as $handle ) {
		wp_dequeue_script( $handle );
	}
	// Jetpack 相关文章:商店场景无用(博客文章保留)
	if ( function_exists( 'is_woocommerce' ) && function_exists( 'is_cart' ) && function_exists( 'is_checkout' )
		&& ( is_woocommerce() || is_cart() || is_checkout() ) ) {
		wp_dequeue_script( 'jetpack_related-posts' );
		wp_dequeue_style( 'jetpack_related-posts' );
	}
}, 9999 );

/** 晚班岗:模板渲染中途才入队的脚本,在页脚打印前再拦一次。 */
add_action( 'wp_print_footer_scripts', function () {
	if ( is_admin() ) { return; }
	foreach ( by_pf_telemetry_handles() as $handle ) {
		wp_dequeue_script( $handle );
		wp_deregister_script( $handle );
	}
}, 0 );

/** 诊断(密钥保护,与 CS 共用 barong_cs_key)。 */
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
		'ok'        => true,
		'version'   => BY_PF_VERSION,
		'telemetry' => by_pf_telemetry_handles(),
		'note'      => 'login-popup components are intentionally kept site-wide',
	) );
	exit;
}, 0 );
