<?php
/**
 * Plugin Name: Barong Email Brand
 * Description: WooCommerce 邮件品牌接管(瘦插件)。① 品牌值存在我们自己的 barong_email_brand 里(REST 可配),在 WooCommerce 读取邮件配色与页眉图时接管返回值,不与它争抢自己的选项;② 经 woocommerce_email_styles 追加家规皮肤,把默认邮件排版换成与站点一致的深色头部+金凤凰、细分隔线表格、柔和地址卡。不改动任何邮件模板结构。
 * Version: 2.0.0
 * Author: Barong Yekhna Console
 */

if ( ! defined( 'ABSPATH' ) ) { exit; }

const BY_EB_VERSION = '2.0.0';
const BY_EB_STORE   = 'barong_email_brand';

/**
 * 我们的品牌值 → WooCommerce 的选项名。
 * WooCommerce 10.x 用 OptionSanitizer 把持着 base/background/body_background/text
 * 四个颜色(写进去会被顶回出厂值),所以这里改为在读取端接管,不写它的库。
 */
function by_eb_map() {
	return array(
		'base'         => 'woocommerce_email_base_color',
		'background'   => 'woocommerce_email_background_color',
		'body_bg'      => 'woocommerce_email_body_background_color',
		'text'         => 'woocommerce_email_text_color',
		'footer_text'  => 'woocommerce_email_footer_text_color',
		'header_image' => 'woocommerce_email_header_image',
	);
}

function by_eb_brand() {
	$raw = json_decode( (string) get_option( BY_EB_STORE, '' ), true );
	return is_array( $raw ) ? $raw : array();
}

/** 品牌值存储:REST 可配(控制台远程管理)。 */
add_action( 'init', function () {
	register_setting( 'options', BY_EB_STORE, array(
		'type'              => 'string',
		'show_in_rest'      => true,
		'default'           => '',
		'sanitize_callback' => function ( $value ) {
			$raw = json_decode( is_string( $value ) ? $value : '', true );
			if ( ! is_array( $raw ) ) { return ''; }
			$clean = array();
			// 皮肤开关不是颜色,单独放行;缺省视为开启。
			if ( isset( $raw['skin'] ) && 'off' === $raw['skin'] ) {
				$clean['skin'] = 'off';
			}
			foreach ( array_keys( by_eb_map() ) as $key ) {
				if ( ! isset( $raw[ $key ] ) ) { continue; }
				$candidate = (string) $raw[ $key ];
				if ( 'header_image' === $key ) {
					$candidate = esc_url_raw( $candidate );
				} elseif ( ! preg_match( '/^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/', $candidate ) ) {
					// 非法色值整条丢弃,绝不把邮件样式写空。
					continue;
				}
				if ( '' !== $candidate ) { $clean[ $key ] = $candidate; }
			}
			return wp_json_encode( $clean );
		},
	) );
} );

/**
 * 读取端接管:只在我们确实配了值时覆盖,没配就原样放行 WooCommerce 自己的值。
 * 用 option_* 过滤器,不写数据库 —— 与 WooCommerce 的清洗器彻底井水不犯河水。
 */
add_action( 'plugins_loaded', function () {
	foreach ( by_eb_map() as $key => $option ) {
		add_filter(
			"option_{$option}",
			function ( $value ) use ( $key ) {
				$brand = by_eb_brand();
				return ( isset( $brand[ $key ] ) && '' !== $brand[ $key ] ) ? $brand[ $key ] : $value;
			},
			99
		);
	}
} );

/**
 * 家规邮件皮肤:经 woocommerce_email_styles 追加在 WooCommerce 自带样式之后,
 * 因此后来者居上。不覆盖模板文件 —— 邮件的 HTML 结构仍是 WooCommerce 原样,
 * 只换视觉;将来 WooCommerce 改版模板也不会因为我们而崩。
 * 可关:品牌值里把 skin 设成 "off"。
 */
function by_eb_skin_css() {
	return <<<'CSS'
/* ===== Barong Yekhna 邮件家规皮肤 ===== */
/* 通过 woocommerce_email_styles 追加,不改任何模板结构。 */

body, #outer_wrapper, #inner_wrapper { background-color:#f4f4f6 !important; }
#wrapper { padding:30px 12px 40px !important; }
#template_container { border-radius:20px !important; border:0 !important; box-shadow:none !important; background-color:transparent !important; }

/* 顶部:凤凰落进墨色区,与标题条连成一整块深色头部 */
#template_header_image { background-color:#1b1a18 !important; padding:36px 24px 2px !important; border-radius:20px 20px 0 0 !important; }
#template_header_image p { margin:0 !important; text-align:center !important; line-height:0 !important; }
#template_header_image img { width:156px !important; max-width:156px !important; height:auto !important; margin:0 auto !important; display:inline-block !important; }

#template_header { background-color:#1b1a18 !important; border:0 !important; border-radius:0 !important; padding:0 30px 32px !important; }
#template_header h1 {
  color:#faf9f6 !important; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif !important;
  font-size:21px !important; font-weight:600 !important; letter-spacing:-0.01em !important;
  text-align:center !important; text-shadow:none !important; line-height:1.4 !important; margin:0 !important; padding:0 !important;
}
#template_header h1 a { color:#faf9f6 !important; }

/* 正文卡片 */
#template_body, #body_content { background-color:#ffffff !important; }
#template_body { border-radius:0 0 20px 20px !important; }
#body_content { border-radius:0 0 20px 20px !important; }
#body_content > table > tbody > tr > td, #body_content table td td { padding:0 !important; }
#body_content > table > tbody > tr > td { padding:32px 34px 26px !important; }
#body_content, #body_content p, #body_content td, #body_content div {
  font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif !important;
  color:#3d3a36 !important; font-size:15px !important; line-height:1.75 !important;
}
#body_content p { margin:0 0 14px !important; }
#body_content h2, #body_content h3 {
  font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif !important;
  color:#1b1a18 !important; letter-spacing:-0.01em !important; font-weight:600 !important;
  margin:26px 0 12px !important; padding:0 !important; text-align:left !important;
}
#body_content h2 { font-size:17px !important; }
#body_content h2 a { color:#1b1a18 !important; text-decoration:none !important; }
#body_content h3 { font-size:15px !important; }

/* 订单表:去掉粗边框,换成克制的细分隔线 */
#body_content table.td, #body_content table { border:0 !important; }
#body_content table td, #body_content table th { border:0 !important; }
#body_content .email-order-details, #body_content table[cellspacing] { border:0 !important; }
#body_content th {
  color:#a49f98 !important; font-size:10.5px !important; letter-spacing:.16em !important;
  text-transform:uppercase !important; font-weight:700 !important;
  border-bottom:1px solid #ececea !important; padding:0 0 11px !important; text-align:left !important;
}
#body_content td.td, #body_content td {
  border-bottom:1px solid #f4f3f1 !important; padding:14px 0 !important; vertical-align:top !important;
}
#body_content .order_item td { color:#3d3a36 !important; }
#body_content .order-totals th { color:#6f6b66 !important; text-transform:none !important; letter-spacing:0 !important; font-size:14px !important; font-weight:500 !important; border-bottom:1px solid #f4f3f1 !important; padding:12px 0 !important; }
#body_content .order-totals td { font-size:14px !important; }
#body_content .order-totals-total th, #body_content .order-totals-total td {
  color:#1b1a18 !important; font-weight:700 !important; font-size:16px !important; border-bottom:0 !important; padding-top:14px !important;
}
#body_content .woocommerce-Price-amount { color:inherit !important; white-space:nowrap !important; }

/* 地址块:与站上的浅色卡片同款 */
#body_content .address, #body_content address {
  background-color:#faf9f6 !important; border:1px solid #ececea !important; border-radius:14px !important;
  padding:16px 18px !important; color:#55524e !important; font-style:normal !important;
  font-size:14px !important; line-height:1.75 !important;
}
#body_content .address a, #body_content address a { color:#55524e !important; }

/* 分隔线 */
#body_content hr, .hr, .hr-top, .hr-bottom { border:0 !important; border-top:1px solid #f0efed !important; margin:26px 0 !important; height:0 !important; background:none !important; }

/* 链接 */
#body_content a { color:#1b1a18 !important; text-decoration:underline !important; }

/* 页脚 */
#template_footer td { padding:20px 10px 0 !important; }
#template_footer #credit, #template_footer #credit p {
  color:#8b867f !important; font-size:12.5px !important; line-height:1.8 !important;
  text-align:center !important; border:0 !important; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif !important;
}
#template_footer #credit a { color:#8b867f !important; }

/* 收掉订单表与合计之间的空行 */
#body_content .email-order-details tbody tr:last-child td { border-bottom:0 !important; padding-bottom:6px !important; }
#body_content .email-order-details tfoot tr:first-child th, #body_content .email-order-details tfoot tr:first-child td { padding-top:16px !important; border-top:1px solid #ececea !important; }
#body_content table + table { margin-top:0 !important; }
/* 结尾致谢与页脚之间别太空 */
#body_content > table > tbody > tr > td { padding-bottom:22px !important; }

/* 收紧各区块之间的呼吸,避免大片空白 */
#body_content hr, .hr, .hr-top, .hr-bottom { margin:18px 0 !important; }
#body_content .email-order-details tfoot tr:first-child th,
#body_content .email-order-details tfoot tr:first-child td { padding-top:14px !important; }
#body_content .order-totals th, #body_content .order-totals td { padding:10px 0 !important; }
#body_content .order-totals-total th, #body_content .order-totals-total td { padding:14px 0 4px !important; }
#body_content h2 { margin-top:22px !important; }
#body_content .address, #body_content address { margin:2px 0 0 !important; }
CSS;
}

add_filter( 'woocommerce_email_styles', function ( $css ) {
	$brand = by_eb_brand();
	if ( isset( $brand['skin'] ) && 'off' === $brand['skin'] ) {
		return $css;
	}
	return $css . "\n" . by_eb_skin_css();
}, 99 );

/** 诊断:品牌值与 WooCommerce 实际读到的值(密钥保护,与 CS 共用 barong_cs_key)。 */
add_action( 'template_redirect', function () {
	if ( ! isset( $_GET['by-eb-ping'] ) ) { return; }
	$secret = (string) get_option( 'barong_cs_key', '' );
	$given  = sanitize_text_field( wp_unslash( $_GET['by-eb-ping'] ) );
	header( 'Content-Type: application/json; charset=UTF-8' );
	if ( '' === $secret || ! hash_equals( $secret, $given ) ) {
		echo wp_json_encode( array( 'ok' => false ) );
		exit;
	}
	$effective = array();
	foreach ( by_eb_map() as $key => $option ) {
		$effective[ $key ] = (string) get_option( $option, '' );
	}
	echo wp_json_encode( array(
		'ok'          => true,
		'version'     => BY_EB_VERSION,
		'brand'       => by_eb_brand(),
		'effective'   => $effective,
		'footer_text' => (string) get_option( 'woocommerce_email_footer_text', '' ),
	) );
	exit;
}, 0 );
