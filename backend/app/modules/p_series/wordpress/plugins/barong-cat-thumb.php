<?php
/**
 * Plugin Name: Barong Category Thumbnail
 * Description: 类目橱窗兜底图(瘦插件)。商店首页按类目展示时,没设缩略图的类目会显示灰占位框——本插件在「显示时」自动借用该类目(含子类目)下第一个商品的主图顶上。只兜底不写库:手动设的缩略图永远优先,后台/REST 仍如实显示「未设置」。诊断:?by-ct-ping=<key>。
 * Version: 1.0.0
 * Author: Barong Yekhna Console
 */

if ( ! defined( 'ABSPATH' ) ) { exit; }

const BY_CT_VERSION    = '1.0.0';
const BY_CT_CACHE_TTL  = 12 * HOUR_IN_SECONDS;
const BY_CT_CACHE_KEY  = 'by_ct_thumb_';

/**
 * 该类目(含子类目)下第一个有主图的已发布商品的图片 id。
 * 找不到返回 0。结果进 transient,避免每次渲染都跑一次查询。
 */
function by_ct_lookup_thumbnail( $term_id ) {
	$term_id = (int) $term_id;
	$cache   = get_transient( BY_CT_CACHE_KEY . $term_id );
	if ( false !== $cache ) {
		return (int) $cache;
	}

	$product_ids = get_posts(
		array(
			'post_type'      => 'product',
			'post_status'    => 'publish',
			'posts_per_page' => 1,
			'fields'         => 'ids',
			'orderby'        => array(
				'menu_order' => 'ASC',
				'date'       => 'DESC',
			),
			'no_found_rows'  => true,
			'meta_query'     => array(
				array(
					'key'     => '_thumbnail_id',
					'compare' => 'EXISTS',
				),
			),
			'tax_query'      => array(
				array(
					'taxonomy'         => 'product_cat',
					'field'            => 'term_id',
					'terms'            => $term_id,
					'include_children' => true,
				),
			),
		)
	);

	$thumb_id = 0;
	if ( $product_ids ) {
		$thumb_id = (int) get_post_thumbnail_id( $product_ids[0] );
	}

	set_transient( BY_CT_CACHE_KEY . $term_id, $thumb_id, BY_CT_CACHE_TTL );
	return $thumb_id;
}

/**
 * 只在前台兜底。后台编辑页和 REST 保持如实——否则用户会以为图已经设好了,
 * 导出的数据源(feed/GMC)也不该看到一张并不属于该类目的图。
 */
function by_ct_should_fallback() {
	if ( is_admin() && ! wp_doing_ajax() ) {
		return false;
	}
	if ( defined( 'REST_REQUEST' ) && REST_REQUEST ) {
		return false;
	}
	if ( defined( 'DOING_CRON' ) && DOING_CRON ) {
		return false;
	}
	return true;
}

/**
 * WooCommerce 渲染类目缩略图时读的就是 term meta 'thumbnail_id'。
 * 在这一层兜底,凡是走 Woo 正规读取的地方(经典模板 / 区块 / 短代码)全都覆盖到。
 *
 * 防重入是硬要求:本回调内部还会 get_term_meta / WP_Query,
 * 不设闸会自我递归(barong 家族踩过全站 502 的坑)。
 */
function by_ct_filter_thumbnail_id( $value, $object_id, $meta_key, $single ) {
	static $busy = false;

	if ( 'thumbnail_id' !== $meta_key || $busy ) {
		return $value;
	}
	if ( null !== $value ) {
		// 别人已经短路了,不抢。
		return $value;
	}
	if ( ! by_ct_should_fallback() ) {
		return $value;
	}

	$busy = true;
	try {
		$term = get_term( (int) $object_id );
		if ( ! $term || is_wp_error( $term ) || 'product_cat' !== $term->taxonomy ) {
			return $value;
		}

		// 手动设过的永远优先。
		$real = get_term_meta( (int) $object_id, 'thumbnail_id', true );
		if ( $real ) {
			return $value;
		}

		$thumb_id = by_ct_lookup_thumbnail( (int) $object_id );
		if ( ! $thumb_id ) {
			return $value;
		}

		// get_term_metadata 的约定:$single 时返回单值,否则返回数组。
		return $single ? (string) $thumb_id : array( (string) $thumb_id );
	} finally {
		$busy = false;
	}
}

add_filter( 'get_term_metadata', 'by_ct_filter_thumbnail_id', 10, 4 );

/** 商品图/归类变了,兜底结果可能过期——清缓存,下次渲染重算。 */
function by_ct_flush_cache() {
	$terms = get_terms(
		array(
			'taxonomy'   => 'product_cat',
			'hide_empty' => false,
			'fields'     => 'ids',
		)
	);
	if ( is_wp_error( $terms ) ) {
		return;
	}
	foreach ( $terms as $term_id ) {
		delete_transient( BY_CT_CACHE_KEY . (int) $term_id );
	}
}

add_action( 'woocommerce_update_product', 'by_ct_flush_cache' );
add_action( 'woocommerce_new_product', 'by_ct_flush_cache' );
add_action( 'deleted_post', 'by_ct_flush_cache' );
add_action( 'edited_product_cat', 'by_ct_flush_cache' );

/**
 * 绕过本插件的兜底,读类目真正存下来的 thumbnail_id。
 * 诊断报告必须用它——否则读到的是自己兜底出来的值,会把「借来的图」
 * 误报成「手动设的图」,报告就骗人了。
 */
function by_ct_raw_thumbnail_id( $term_id ) {
	remove_filter( 'get_term_metadata', 'by_ct_filter_thumbnail_id', 10 );
	$real = (int) get_term_meta( (int) $term_id, 'thumbnail_id', true );
	add_filter( 'get_term_metadata', 'by_ct_filter_thumbnail_id', 10, 4 );
	return $real;
}

/** 诊断(密钥保护,与 CS 共用 barong_cs_key)。列出每个类目当前解析到的图。 */
add_action(
	'template_redirect',
	function () {
		if ( ! isset( $_GET['by-ct-ping'] ) ) { return; }
		$secret = (string) get_option( 'barong_cs_key', '' );
		$given  = sanitize_text_field( wp_unslash( $_GET['by-ct-ping'] ) );
		header( 'Content-Type: application/json; charset=UTF-8' );
		if ( '' === $secret || ! hash_equals( $secret, $given ) ) {
			echo wp_json_encode( array( 'ok' => false ) );
			exit;
		}

		$report = array();
		$terms  = get_terms(
			array(
				'taxonomy'   => 'product_cat',
				'hide_empty' => false,
			)
		);
		if ( ! is_wp_error( $terms ) ) {
			foreach ( $terms as $term ) {
				$real     = by_ct_raw_thumbnail_id( $term->term_id );
				$fallback = by_ct_lookup_thumbnail( $term->term_id );
				$report[] = array(
					'term_id'     => $term->term_id,
					'name'        => $term->name,
					'count'       => $term->count,
					'manual_id'   => $real,
					'fallback_id' => $fallback,
					'source'      => $real ? 'manual' : ( $fallback ? 'fallback' : 'none' ),
				);
			}
		}

		echo wp_json_encode(
			array(
				'ok'         => true,
				'version'    => BY_CT_VERSION,
				'categories' => $report,
			)
		);
		exit;
	},
	0
);
