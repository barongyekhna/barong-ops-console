<?php
/**
 * Plugin Name: Barong Perf
 * Description: 前台脚本减负(瘦插件)。只卸真正无买家价值的脚本:WooPayments 前台遥测(早晚两道岗,防渲染中途入队)、Jetpack 相关文章不进商店页。登录弹窗相关组件(密码强度/Google 登录)保留——Flatsome 全站渲染登录弹窗,它们是在岗的。诊断:?by-pf-ping=<key>。
 * Version: 1.2.0
 * Author: Barong Yekhna Console
 */

if ( ! defined( 'ABSPATH' ) ) { exit; }

const BY_PF_VERSION = '1.2.0';

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

/**
 * LCP 修复(v1.2, 2026-07-23 PageSpeed 实锤):主题给商品主图同时标
 * fetchpriority=high 和 loading=lazy,懒加载赢,首屏主图被人为推迟。
 * 规则一:声明了最高优先的图,永不懒加载。
 */
add_filter( 'wp_get_attachment_image_attributes', function ( $attr ) {
	if ( isset( $attr['fetchpriority'], $attr['loading'] ) && 'high' === $attr['fetchpriority'] ) {
		unset( $attr['loading'] );
	}
	return $attr;
}, 9999 );

/** 规则二(Woo 官方口):图库主图强制立即加载。 */
add_filter( 'woocommerce_gallery_image_html_attachment_image_params', function ( $params, $attachment_id, $image_size, $main_image ) {
	if ( $main_image ) {
		$params['loading']       = 'eager';
		$params['fetchpriority'] = 'high';
	}
	return $params;
}, 10, 4 );

/** 规则三:产品页 <head> 预载主图,浏览器解析 HTML 时即开始取图。 */
add_action( 'wp_head', function () {
	if ( ! function_exists( 'is_product' ) || ! is_product() ) { return; }
	$thumb_id = get_post_thumbnail_id();
	if ( ! $thumb_id ) { return; }
	$src = wp_get_attachment_image_src( $thumb_id, 'woocommerce_single' );
	if ( ! $src || empty( $src[0] ) ) { return; }
	printf(
		'<link rel="preload" as="image" href="%s" fetchpriority="high">' . "\n",
		esc_url( $src[0] )
	);
}, 2 );

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
		'note'      => 'v1.2: LCP main-image never lazy + head preload',
	) );
	exit;
}, 0 );
