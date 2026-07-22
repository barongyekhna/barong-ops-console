<?php
/**
 * Plugin Name: Barong Related Guard
 * Description: 相关商品栅栏(瘦插件)。相关推荐/追加销售候选必须与当前商品同属一个顶级类目树——露营炊具页绝不推荐唇釉。只做过滤不做注入;同树无候选时宁可少推不乱推。诊断:?by-rg-ping=<key>。
 * Version: 1.0.0
 * Author: Barong Yekhna Console
 */

if ( ! defined( 'ABSPATH' ) ) { exit; }

const BY_RG_VERSION = '1.0.0';

/** 商品所属的顶级类目 id 集合(沿 product_cat 树向上爬到根)。 */
function by_rg_top_ancestors( $product_id ) {
	$tops  = array();
	$terms = get_the_terms( $product_id, 'product_cat' );
	if ( ! is_array( $terms ) ) {
		return $tops;
	}
	foreach ( $terms as $term ) {
		$ancestors = get_ancestors( $term->term_id, 'product_cat' );
		$top       = $ancestors ? end( $ancestors ) : $term->term_id;
		$tops[ (int) $top ] = true;
	}
	return array_keys( $tops );
}

/** 过滤:候选与当前商品必须共享至少一个顶级类目。 */
function by_rg_filter_related( $related_ids, $product_id ) {
	if ( ! is_array( $related_ids ) || ! $related_ids ) {
		return $related_ids;
	}
	$current_tops = by_rg_top_ancestors( $product_id );
	if ( ! $current_tops ) {
		return $related_ids;
	}
	$allowed = array();
	foreach ( $related_ids as $candidate_id ) {
		$candidate_tops = by_rg_top_ancestors( $candidate_id );
		if ( array_intersect( $current_tops, $candidate_tops ) ) {
			$allowed[] = $candidate_id;
		}
	}
	return $allowed;
}

add_filter( 'woocommerce_related_products', 'by_rg_filter_related', 10, 2 );

/** 标签匹配会把不同类目树的商品扯到一起,关掉——只按类目找相关。 */
add_filter( 'woocommerce_product_related_posts_relate_by_tag', '__return_false' );

/** 诊断(密钥保护,与 CS 共用 barong_cs_key)。 */
add_action( 'template_redirect', function () {
	if ( ! isset( $_GET['by-rg-ping'] ) ) { return; }
	$secret = (string) get_option( 'barong_cs_key', '' );
	$given  = sanitize_text_field( wp_unslash( $_GET['by-rg-ping'] ) );
	header( 'Content-Type: application/json; charset=UTF-8' );
	if ( '' === $secret || ! hash_equals( $secret, $given ) ) {
		echo wp_json_encode( array( 'ok' => false ) );
		exit;
	}
	echo wp_json_encode( array( 'ok' => true, 'version' => BY_RG_VERSION ) );
	exit;
}, 0 );
