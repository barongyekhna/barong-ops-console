<?php
/**
 * Plugin Name: Barong GEO Archive Filter
 * Description: Keeps GEO buying guides out of the blog archive and feeds. The category list is remote-controlled by the console — this plugin holds no hard-coded ids.
 * Version: 1.0.0
 * Author: Barong Yekhna
 *
 * Guides are published as regular posts (they share the site's Google-taxonomy
 * category tree with products, which is the whole point). The side effect is that
 * they flood `page_for_posts` — the blog archive reserved for editorial content.
 *
 * This filters the MAIN query only, on the blog archive and feeds. Category
 * archives, single posts, sitemaps, search and admin are all untouched: a guide
 * must stay fully indexable and findable, it just should not headline the blog.
 *
 * Control plane: the console writes the id list into the `barong_geo_category_ids`
 * option over REST, so new Google categories start being excluded the moment they
 * are created — this file never needs to be re-uploaded.
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

const BARONG_GEO_ARCHIVE_OPTION = 'barong_geo_category_ids';

/**
 * Expose the option to the REST API so the console can keep it in sync.
 */
function barong_geo_archive_register_setting() {
	register_setting(
		'options',
		BARONG_GEO_ARCHIVE_OPTION,
		array(
			'type'         => 'string',
			'description'  => 'Comma-separated category ids GEO owns; excluded from the blog archive.',
			'default'      => '',
			'show_in_rest' => true,
			'sanitize_callback' => 'barong_geo_archive_sanitize',
		)
	);
}
add_action( 'init', 'barong_geo_archive_register_setting' );

/**
 * Only ever store a comma-separated list of plausible term ids.
 *
 * Deliberately not `absint()`: it turns "-5" into 5, so a typo or a mangled
 * payload would silently exclude a real, unrelated category (caught in local
 * testing 2026-07-29). Anything that is not already a plain positive integer is
 * dropped rather than coerced.
 */
function barong_geo_archive_sanitize( $value ) {
	$ids = array();
	foreach ( explode( ',', (string) $value ) as $part ) {
		$part = trim( $part );
		if ( '' === $part || ! preg_match( '/^[0-9]{1,10}$/', $part ) ) {
			continue;
		}
		$id = (int) $part;
		if ( $id > 0 ) {
			$ids[ $id ] = $id;
		}
	}
	return implode( ',', array_values( $ids ) );
}

/**
 * @return int[] The category ids the console currently owns.
 */
function barong_geo_archive_ids() {
	// Parsed with the same strict rule as the sanitiser: the option can also be
	// written by WP-CLI or straight into the database, and coercing a malformed
	// value would exclude a real, unrelated category from the blog.
	$raw = get_option( BARONG_GEO_ARCHIVE_OPTION, '' );
	$ids = array();
	foreach ( explode( ',', (string) $raw ) as $part ) {
		$part = trim( $part );
		if ( '' === $part || ! preg_match( '/^[0-9]{1,10}$/', $part ) ) {
			continue;
		}
		$id = (int) $part;
		if ( $id > 0 ) {
			$ids[] = $id;
		}
	}
	return $ids;
}

/**
 * Drop GEO categories from the blog archive and feeds.
 *
 * Guarded hard: admin screens, secondary queries, single posts, category
 * archives, search and sitemaps must all behave exactly as before.
 */
function barong_geo_archive_filter( $query ) {
	if ( is_admin() || ! $query instanceof WP_Query || ! $query->is_main_query() ) {
		return;
	}
	// Blog archive (page_for_posts or a site with posts on front) and feeds only.
	if ( ! $query->is_home() && ! $query->is_feed() ) {
		return;
	}
	$ids = barong_geo_archive_ids();
	if ( empty( $ids ) ) {
		return;
	}
	$existing = (array) $query->get( 'category__not_in', array() );
	$query->set( 'category__not_in', array_values( array_unique( array_merge( $existing, $ids ) ) ) );
}
add_action( 'pre_get_posts', 'barong_geo_archive_filter' );
