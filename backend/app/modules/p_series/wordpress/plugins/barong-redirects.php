<?php
/**
 * Plugin Name: Barong Redirects
 * Description: 404 治理(瘦插件)。① 控制台遥控的 301 跳转表(REST 写 barong_redirect_map,只在 404 时生效,永不劫持正常页面);② 品牌版 404 页面(家规文案 + 去商店/联系我们的真链接)。
 * Version: 1.2.0
 * Author: Barong Yekhna Console
 */

if ( ! defined( 'ABSPATH' ) ) { exit; }

const BY_RD_OPTION  = 'barong_redirect_map';
const BY_RD_VERSION = '1.2.0';

/** 跳转表:REST 可配(与 house-style 同模式,控制台远程管理)。 */
add_action( 'init', function () {
	register_setting( 'options', BY_RD_OPTION, array(
		'type'              => 'string',
		'show_in_rest'      => true,
		'default'           => '',
		'sanitize_callback' => function ( $value ) {
			$value   = is_string( $value ) ? $value : '';
			$decoded = json_decode( $value, true );
			return is_array( $decoded ) ? wp_json_encode( $decoded ) : '';
		},
	) );
} );

/** 键规范化:小写、去尾斜杠、空路径归一为 "/"。 */
function by_rd_normalize( $path ) {
	$path = strtolower( trim( (string) $path ) );
	$path = rtrim( $path, '/' );
	return '' === $path ? '/' : $path;
}

/**
 * 只在 404 命中时跳转 —— 安全底线:正常页面永远不会被这张表影响。
 * 支持两种键:纯路径(/old-page)与带查询串的整串(/?page_id=1759)。
 */
add_action( 'template_redirect', function () {
	if ( is_admin() || ! is_404() ) { return; }

	$map = json_decode( (string) get_option( BY_RD_OPTION, '' ), true );
	if ( ! is_array( $map ) || ! $map ) { return; }

	$uri   = isset( $_SERVER['REQUEST_URI'] ) ? wp_unslash( $_SERVER['REQUEST_URI'] ) : '/';
	$path  = by_rd_normalize( wp_parse_url( $uri, PHP_URL_PATH ) );
	$whole = by_rd_normalize( $uri );

	$target = null;
	foreach ( array( $whole, $path ) as $candidate ) {
		foreach ( $map as $from => $to ) {
			if ( by_rd_normalize( $from ) === $candidate ) {
				$target = (string) $to;
				break 2;
			}
		}
	}
	if ( null === $target || '' === $target ) { return; }

	// 目标一律解析成本站地址,杜绝被写成外站开放跳转。
	$dest = ( 0 === strpos( $target, 'http' ) ) ? $target : home_url( $target );
	wp_safe_redirect( wp_validate_redirect( $dest, home_url( '/' ) ), 301 );
	exit;
}, 1 );

/* ============ 品牌版 404 页面 ============ */

/**
 * 主题默认英文文案 → 家规文案(真文字,可选中、可被读屏软件读到)。
 *
 * 【事故教训 · 死规矩】这个过滤器只能在 template_redirect 之后挂载,
 * 且回调内**绝不能**调用 is_404() 等条件判断函数:gettext 会在查询建立之前
 * 就被其它插件触发,此时 is_404() 触发 _doing_it_wrong(),而它自己要调 __()
 * 翻译报警文案 → 又回到本过滤器 → 无限递归 → PHP 崩溃 → 全站 502。
 * (2026-07-20 生产事故,本地已复现并验证修法。)
 */
function by_rd_404_copy( $translated, $text, $domain ) {
	if ( 'Oops! That page can&rsquo;t be found.' === $text || "Oops! That page can’t be found." === $text ) {
		return 'That page isn’t here.';
	}
	if ( 0 === strpos( $text, 'It looks like nothing was found at this location' ) ) {
		return 'The link may be out of date, or the piece may have been retired. Search below, or start from the collection — every piece is chosen and checked one at a time.';
	}
	return $translated;
}

/** 在 404 区块尾部注入两个真按钮(找不到锚点就什么都不做,fail-safe)。 */
function by_rd_404_inject( $html ) {
	$cta = '<div class="by-404-cta">'
		. '<a class="by-404-btn" href="' . esc_url( home_url( '/shop-2/' ) ) . '">Browse the collection</a>'
		. '<a class="by-404-btn ghost" href="' . esc_url( home_url( '/contact/' ) ) . '">Contact us</a>'
		. '</div>';
	$out = preg_replace(
		'#(<section class="error-404[^"]*"[^>]*>.*?)(</section>)#s',
		'$1' . $cta . '$2',
		$html,
		1
	);
	return ( null === $out || '' === $out ) ? $html : $out;
}

/** 两者都只在查询已建立、且确认是 404 之后才挂载 —— 这是本插件的安全底线。 */
add_action( 'template_redirect', function () {
	if ( is_admin() || ! is_404() ) { return; }
	add_filter( 'gettext', 'by_rd_404_copy', 10, 3 );
	ob_start( 'by_rd_404_inject' );
}, 20 );

/** 诊断:当前跳转表(密钥保护,与 CS 共用 barong_cs_key)。 */
add_action( 'template_redirect', function () {
	if ( ! isset( $_GET['by-rd-ping'] ) ) { return; }
	$secret = (string) get_option( 'barong_cs_key', '' );
	$given  = sanitize_text_field( wp_unslash( $_GET['by-rd-ping'] ) );
	header( 'Content-Type: application/json; charset=UTF-8' );
	if ( '' === $secret || ! hash_equals( $secret, $given ) ) {
		echo wp_json_encode( array( 'ok' => false ) );
		exit;
	}
	$map = json_decode( (string) get_option( BY_RD_OPTION, '' ), true );
	echo wp_json_encode( array(
		'ok'      => true,
		'version' => BY_RD_VERSION,
		'rules'   => is_array( $map ) ? count( $map ) : 0,
		'map'     => is_array( $map ) ? $map : array(),
	) );
	exit;
}, 0 );
