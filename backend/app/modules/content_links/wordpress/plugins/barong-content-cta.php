<?php
/**
 * Plugin Name: Barong Content CTA
 * Description: 文章页的产品卡片 CTA 与相关内容推荐。数据来自控制台推送的 barong_content_links option，样式参数来自 barong_content_cta_style——本文件永不需要重新上传。
 * Version: 1.0.0
 * Author: Barong Yekhna
 *
 * 为什么存在：站内文章原来的"内链"渲染出来就是一行裸蓝字，没有按钮、没有卡片、
 * 没有任何样式。C 端选购指南写得再好，读者读完看到的是一行小蓝字，转化就没了。
 *
 * ## 为什么由插件渲染，而不是把链接写进文章正文
 *
 * 写进正文意味着每次新产品上架、新指南发布，都要**读改写 N 篇文章**：
 * WP REST 默认返回 content.rendered（过完 the_content 全套过滤器），取错一次
 * 就把渲染后的 HTML 写回 post_content，文章永久变形；而且人一旦在 WP 里手改过
 * 一篇，区块编辑器会插 <!-- wp:html --> 分隔符，替换行为不再可预测。
 *
 * 改成渲染时查表之后：**控制台只写一个 option**（不管站上 10 篇还是 500 篇），
 * 文章 HTML 一个字节不碰，所以不用重新审稿、不用重跑品牌门，而且链接天然永远最新。
 *
 * SEO 效果完全相同——the_content 是服务端 PHP，Google 看到的就是渲染后的 HTML。
 *
 * ## 两条红线（业务约束，不是样式偏好）
 *
 * 1. **卡片上绝不出现价格。** GMC 会把「页面价与 feed 价不符」判成
 *    Misrepresentation，这个账号已经因此被封过两次，只剩一次申诉机会。
 *    文章页上出现产品价格 = 又开一个价格面。契约层就没有价格字段。
 * 2. **绝不进任何 schema.org / itemprop。** 结构化数据只能从产品页出，
 *    文章页再出一份会让爬虫看到两个互相矛盾的产品实体。
 *
 * ## 和 Barong B2B Widget 共存
 *
 * b2b 那个插件已经在 the_content @20 追加一行「Buying for a store?」。
 * 本插件挂 @15（正文中段产品卡片）和 @18（文末相关内容），批发那行落在最后。
 * 阅读顺序：正文 → 产品卡片 → 相关指南/工艺文 → 批发。
 * **本插件绝不渲染任何批发链接**——那是 b2b 的地盘，两边都渲染就会出现两遍。
 *
 * ## 图片走附件 id
 *
 * 控制台给的是 WP 附件 id（从 Woo 的 images[0].id 来）。用
 * wp_get_attachment_image() 渲染能自动出 srcset / width / height / loading=lazy，
 * **零布局抖动**，而且走 WP 已经生成好的缩略图，不会把 2000px 原图塞进 300px 卡片。
 * 附件被删掉时才降级到控制台给的原始 URL。
 *
 * 前台专用：admin / REST / cron / feed 一律跳过。
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

const BY_CTA_VERSION      = '1.0.0';
const BY_CTA_LINKS_OPTION = 'barong_content_links';
const BY_CTA_STYLE_OPTION = 'barong_content_cta_style';
const BY_CTA_VER_OPTION   = 'barong_content_cta_ver';

/**
 * 两个 option 分开：改一次卡片颜色不该重推几十 KB 的链接图。
 */
function by_cta_register_settings() {
	register_setting(
		'options',
		BY_CTA_LINKS_OPTION,
		array(
			'type'              => 'string',
			'description'       => 'JSON: 全站链接图（控制台管理）。',
			'default'           => '',
			'show_in_rest'      => true,
			'sanitize_callback' => 'by_cta_sanitize_json',
		)
	);
	register_setting(
		'options',
		BY_CTA_STYLE_OPTION,
		array(
			'type'              => 'string',
			'description'       => 'JSON: CTA 卡片的样式参数（控制台管理）。',
			'default'           => '',
			'show_in_rest'      => true,
			'sanitize_callback' => 'by_cta_sanitize_json',
		)
	);
}
add_action( 'init', 'by_cta_register_settings' );

/** 坏 JSON 一律存空串——宁可什么都不渲染，也不让半截数据上前台。 */
function by_cta_sanitize_json( $value ) {
	$text = is_string( $value ) ? trim( $value ) : '';
	if ( '' === $text ) {
		return '';
	}
	$parsed = json_decode( $text, true );
	return is_array( $parsed ) ? $text : '';
}

/**
 * 链接图有几十 KB。update_option 新建的 option 默认 autoload=yes，
 * **每一个请求**（含后台、含 REST）都会把它加载进内存 —— 全站变慢。
 * 用一个版本 option 做闩，只在版本变化时关一次。
 */
function by_cta_ensure_autoload_off() {
	if ( get_option( BY_CTA_VER_OPTION ) === BY_CTA_VERSION ) {
		return;
	}
	// ⚠️ option 还不存在时 wp_set_option_autoload 无事可做。这时候**绝不能落闩**——
	// 否则以后控制台第一次推送创建它，会带着默认的 autoload=yes 永远关不掉，
	// 几十 KB 的链接图就会在每一个请求（含后台、含 REST）里被加载。
	// 2026-07-31 本地实测踩到：装上插件时 option 还没推过。
	if ( false === get_option( BY_CTA_LINKS_OPTION, false ) ) {
		return;
	}
	if ( function_exists( 'wp_set_option_autoload' ) ) {
		wp_set_option_autoload( BY_CTA_LINKS_OPTION, 'no' );
	}
	update_option( BY_CTA_VER_OPTION, BY_CTA_VERSION, false );
}
add_action( 'init', 'by_cta_ensure_autoload_off', 20 );

/** 前台专用。和 by_b2b_should_render 同规。 */
function by_cta_should_render() {
	if ( is_admin() ) {
		return false;
	}
	if ( defined( 'REST_REQUEST' ) && REST_REQUEST ) {
		return false;
	}
	if ( defined( 'DOING_CRON' ) && DOING_CRON ) {
		return false;
	}
	if ( is_feed() ) {
		return false;
	}
	if ( ! is_singular( 'post' ) || ! in_the_loop() || ! is_main_query() ) {
		return false;
	}
	return true;
}

function by_cta_map() {
	static $cache = null;
	if ( null !== $cache ) {
		return $cache;
	}
	$raw    = (string) get_option( BY_CTA_LINKS_OPTION, '' );
	$parsed = $raw ? json_decode( $raw, true ) : null;
	$cache  = is_array( $parsed ) ? $parsed : array();
	return $cache;
}

function by_cta_style() {
	static $cache = null;
	if ( null !== $cache ) {
		return $cache;
	}
	$raw    = (string) get_option( BY_CTA_STYLE_OPTION, '' );
	$parsed = $raw ? json_decode( $raw, true ) : null;
	$cache  = is_array( $parsed ) ? $parsed : array();
	return $cache;
}

/** 这篇文章该挂什么。没有条目就返回空数组——绝不渲染空盒子。 */
function by_cta_entry_for_current_post() {
	$map   = by_cta_map();
	$posts = isset( $map['posts'] ) && is_array( $map['posts'] ) ? $map['posts'] : array();
	$id    = (string) get_the_ID();
	return isset( $posts[ $id ] ) && is_array( $posts[ $id ] ) ? $posts[ $id ] : array();
}

/**
 * 样式只输出一次。**刻意内联**：卡片要在任何主题下都长得一样，不依赖那个
 * 靠人工上传的 house-style 注入器，也不多发一个 HTTP 请求。
 * （抄的是 by_b2b_styles_once 的成熟做法。）
 */
function by_cta_styles_once() {
	static $printed = false;
	if ( $printed ) {
		return '';
	}
	$printed = true;
	$style   = by_cta_style();
	$accent  = isset( $style['accent'] ) ? sanitize_hex_color( $style['accent'] ) : '';
	$accent  = $accent ? $accent : '#111111';
	$radius  = isset( $style['radius'] ) ? (int) $style['radius'] : 12;
	$radius  = max( 0, min( 32, $radius ) );

	ob_start();
	?>
	<style id="by-cta-css">
	.by-cta{margin:28px 0;display:grid;gap:14px}
	.by-cta-card{display:flex;gap:14px;align-items:center;border:1px solid rgba(0,0,0,.10);
	 border-radius:<?php echo (int) $radius; ?>px;padding:12px;background:#fff;text-decoration:none;color:inherit}
	.by-cta-card:hover{border-color:rgba(0,0,0,.28)}
	.by-cta-thumb{flex:none;width:88px;height:88px;overflow:hidden;border-radius:8px;background:#f4f3f1}
	.by-cta-thumb img{width:100%;height:100%;object-fit:cover;display:block}
	.by-cta-body{flex:1;min-width:0}
	.by-cta-eyebrow{font-size:11px;letter-spacing:.08em;text-transform:uppercase;opacity:.55;
	 margin:0 0 3px}
	.by-cta-name{font-size:15px;line-height:1.35;margin:0 0 8px;font-weight:600}
	.by-cta-btn{display:inline-block;background:<?php echo esc_attr( $accent ); ?>;color:#fff;
	 border-radius:999px;padding:7px 16px;font-size:13px;line-height:1.2;text-decoration:none}
	.by-cta-links{margin:26px 0 0;border-top:1px solid rgba(0,0,0,.10);padding-top:16px}
	.by-cta-links h3{font-size:14px;letter-spacing:.04em;text-transform:uppercase;opacity:.6;
	 margin:0 0 8px}
	.by-cta-links ul{margin:0 0 14px;padding-left:18px}
	.by-cta-links li{margin:5px 0;line-height:1.45}
	@media (max-width:520px){.by-cta-thumb{width:66px;height:66px}}
	</style>
	<?php
	return (string) ob_get_clean();
}

/** 一张产品卡片。价格与 schema 绝不出现（见文件头两条红线）。 */
function by_cta_render_card( $card ) {
	$name = isset( $card['n'] ) ? (string) $card['n'] : '';
	$url  = isset( $card['u'] ) ? (string) $card['u'] : '';
	if ( '' === $name || '' === $url ) {
		return '';
	}
	$style = by_cta_style();
	$label = isset( $style['button'] ) && $style['button']
		? (string) $style['button']
		: 'View product';
	$eyebrow = isset( $style['eyebrow'] ) && $style['eyebrow']
		? (string) $style['eyebrow']
		: 'Made by us';

	$thumb = '';
	$attachment = isset( $card['i'] ) ? (int) $card['i'] : 0;
	if ( $attachment > 0 && wp_attachment_is_image( $attachment ) ) {
		// 附件 id 能出 srcset / width / height / loading=lazy —— 零布局抖动。
		$thumb = wp_get_attachment_image(
			$attachment,
			'woocommerce_thumbnail',
			false,
			array( 'alt' => $name, 'loading' => 'lazy' )
		);
	}
	if ( '' === $thumb && ! empty( $card['s'] ) ) {
		// 附件被删了才降级到原始 URL。
		$thumb = '<img src="' . esc_url( (string) $card['s'] ) . '" alt="'
			. esc_attr( $name ) . '" loading="lazy" width="88" height="88">';
	}

	$out  = '<a class="by-cta-card" href="' . esc_url( $url ) . '">';
	if ( $thumb ) {
		$out .= '<span class="by-cta-thumb">' . $thumb . '</span>';
	}
	$out .= '<span class="by-cta-body">';
	$out .= '<span class="by-cta-eyebrow">' . esc_html( $eyebrow ) . '</span>';
	$out .= '<span class="by-cta-name">' . esc_html( $name ) . '</span>';
	$out .= '<span class="by-cta-btn">' . esc_html( $label ) . '</span>';
	$out .= '</span></a>';
	return $out;
}

/**
 * 遗留区块清理：老文章正文里可能还留着控制台早期直接拼进去的链接块。
 * 在这里摘掉，**不用把所有文章重发一遍**（重发要过审阅状态门）。
 */
function by_cta_strip_legacy( $content ) {
	$content = preg_replace(
		'#<div class="barong-seo-links">.*?</div>#is',
		'',
		(string) $content
	);
	return (string) $content;
}

/**
 * 正文中段的产品卡片。位置靠**现场数 h2**——因为是渲染时计算，
 * 不需要在正文里埋锚点（GEO 文章的 section 全是同一个 class，埋了也找不回来）。
 */
function by_cta_product_card( $content ) {
	static $done = false;
	// the_content 一个请求会被摘要 / 相关文章 / SEO 插件触发多次。
	if ( $done || ! by_cta_should_render() ) {
		return $content;
	}
	$done    = true;
	$content = by_cta_strip_legacy( $content );

	$entry = by_cta_entry_for_current_post();
	$ids   = isset( $entry['p'] ) && is_array( $entry['p'] ) ? $entry['p'] : array();
	if ( ! $ids ) {
		return $content;
	}
	$map   = by_cta_map();
	$cards = isset( $map['p'] ) && is_array( $map['p'] ) ? $map['p'] : array();
	$style = by_cta_style();
	$limit = isset( $style['max_cards'] ) ? (int) $style['max_cards'] : 2;
	$limit = max( 1, min( 3, $limit ) );

	$html = '';
	foreach ( array_slice( $ids, 0, $limit ) as $id ) {
		$key = (string) $id;
		if ( isset( $cards[ $key ] ) && is_array( $cards[ $key ] ) ) {
			$html .= by_cta_render_card( $cards[ $key ] );
		}
	}
	if ( '' === $html ) {
		return $content;
	}
	$block = by_cta_styles_once() . '<div class="by-cta">' . $html . '</div>';

	// 插在第 2 个 h2 之前；不够两个 h2 就落文末。
	if ( preg_match_all( '/<h2[\s>]/i', $content, $m, PREG_OFFSET_CAPTURE ) ) {
		if ( count( $m[0] ) >= 2 ) {
			$at = (int) $m[0][1][1];
			return substr( $content, 0, $at ) . $block . substr( $content, $at );
		}
	}
	return $content . $block;
}
add_filter( 'the_content', 'by_cta_product_card', 15 );

/** 文末的相关指南 / 工艺文。**不渲染批发链接**——那是 b2b 插件 @20 的地盘。 */
function by_cta_related_links( $content ) {
	static $done = false;
	if ( $done || ! by_cta_should_render() ) {
		return $content;
	}
	$done  = true;
	$entry = by_cta_entry_for_current_post();
	if ( ! $entry ) {
		return $content;
	}
	$map    = by_cta_map();
	$groups = array(
		array( 'g', 'Related guides' ),
		array( 'f', 'How we make it' ),
	);

	$html = '';
	foreach ( $groups as $group ) {
		list( $key, $heading ) = $group;
		$ids = isset( $entry[ $key ] ) && is_array( $entry[ $key ] ) ? $entry[ $key ] : array();
		$dir = isset( $map[ $key ] ) && is_array( $map[ $key ] ) ? $map[ $key ] : array();
		$items = '';
		foreach ( $ids as $id ) {
			$row = isset( $dir[ (string) $id ] ) ? $dir[ (string) $id ] : null;
			if ( ! is_array( $row ) || empty( $row['t'] ) || empty( $row['u'] ) ) {
				continue;
			}
			$items .= '<li><a href="' . esc_url( (string) $row['u'] ) . '">'
				. esc_html( (string) $row['t'] ) . '</a></li>';
		}
		if ( $items ) {
			$html .= '<h3>' . esc_html( $heading ) . '</h3><ul>' . $items . '</ul>';
		}
	}
	if ( '' === $html ) {
		return $content;
	}
	return $content . by_cta_styles_once()
		. '<div class="by-cta-links">' . $html . '</div>';
}
add_filter( 'the_content', 'by_cta_related_links', 18 );

/**
 * 诊断 ping。插件被停用 = 全站文章的卡片一次性消失，必须能在哨兵面板看见。
 */
function by_cta_ping() {
	if ( ! isset( $_GET['by-cta-ping'] ) ) {
		return;
	}
	$expected = (string) get_option( 'barong_cs_key', '' );
	if ( '' === $expected
		|| ! hash_equals( $expected, (string) wp_unslash( $_GET['by-cta-ping'] ) ) ) {
		return;
	}
	$map = by_cta_map();
	wp_send_json(
		array(
			'ok'              => true,
			'version'         => BY_CTA_VERSION,
			'posts_mapped'    => isset( $map['posts'] ) ? count( (array) $map['posts'] ) : 0,
			'products_mapped' => isset( $map['p'] ) ? count( (array) $map['p'] ) : 0,
		)
	);
}
add_action( 'init', 'by_cta_ping', 30 );
