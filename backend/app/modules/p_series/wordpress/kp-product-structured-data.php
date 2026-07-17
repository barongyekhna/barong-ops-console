<?php
/**
 * Plugin Name: Barong K Product Structured Data
 * Description: Projects publishable K data into the active Woo/Yoast Product graph.
 * Version: 1.1.0
 *
 * Deploy as a WordPress must-use plugin. Yoast WooCommerce SEO owns the live
 * Product graph on the production site, while WooCommerce core remains a
 * supported fallback. Both paths call the same projector so they cannot drift.
 */

defined( 'ABSPATH' ) || exit;

/**
 * Resolve the product for filters (such as wpseo_schema_product) that do not
 * pass a WC_Product instance.
 *
 * @param mixed $candidate Possible product supplied by a filter.
 * @return WC_Product|null
 */
function barong_k_schema_product( $candidate = null ) {
	if ( is_a( $candidate, 'WC_Product' ) ) {
		return $candidate;
	}

	global $product;
	if ( is_a( $product, 'WC_Product' ) ) {
		return $product;
	}

	if ( ! function_exists( 'wc_get_product' ) ) {
		return null;
	}
	$post_id = function_exists( 'get_queried_object_id' )
		? get_queried_object_id()
		: 0;
	if ( ! $post_id ) {
		return null;
	}
	$resolved = wc_get_product( $post_id );
	return is_a( $resolved, 'WC_Product' ) ? $resolved : null;
}

/**
 * Decode authored plain text before it enters JSON-LD.
 *
 * @param mixed $value Authored metadata value.
 * @return string
 */
function barong_k_schema_plain_text( $value ) {
	if ( ! is_scalar( $value ) ) {
		return '';
	}
	$charset = function_exists( 'get_bloginfo' )
		? get_bloginfo( 'charset' )
		: 'UTF-8';
	$charset = $charset ? $charset : 'UTF-8';
	$decoded = html_entity_decode(
		(string) $value,
		ENT_QUOTES | ENT_HTML5,
		$charset
	);
	return trim( sanitize_text_field( $decoded ) );
}

/**
 * Read the short K SEO title written by the P workflow. The Woo title is only
 * a compatibility fallback; product HTML is never stripped to manufacture it.
 *
 * @param WC_Product $product Product being rendered.
 * @return string
 */
function barong_k_schema_name( $product ) {
	$name = barong_k_schema_plain_text(
		$product->get_meta( '_yoast_wpseo_title', true )
	);
	if ( '' === $name || false !== strpos( $name, '%%' ) ) {
		$name = barong_k_schema_plain_text( $product->get_name() );
	}
	return $name;
}

/**
 * Read K's authored seo.meta_description. Missing metadata deliberately means
 * no schema description: falling back to stripped product HTML caused joined
 * words in the live graph and is forbidden by the upload contract.
 *
 * @param WC_Product $product Product being rendered.
 * @return string
 */
function barong_k_schema_description( $product ) {
	return barong_k_schema_plain_text(
		$product->get_meta( '_yoast_wpseo_metadesc', true )
	);
}

/**
 * Validate the supplier-backed PropertyValue list stored by n8n.
 *
 * @param WC_Product $product Product being rendered.
 * @return array<int, array<string, string>>
 */
function barong_k_schema_properties( $product ) {
	$raw = $product->get_meta( '_kp_additional_property', true );
	if ( ! is_string( $raw ) || '' === trim( $raw ) ) {
		return array();
	}
	$decoded = json_decode( $raw, true );
	if ( ! is_array( $decoded ) ) {
		return array();
	}

	$properties = array();
	foreach ( array_slice( $decoded, 0, 100 ) as $item ) {
		if (
			! is_array( $item ) ||
			! isset( $item['name'], $item['value'] ) ||
			! is_scalar( $item['name'] ) ||
			! is_scalar( $item['value'] )
		) {
			continue;
		}
		$name  = barong_k_schema_plain_text( $item['name'] );
		$value = barong_k_schema_plain_text( $item['value'] );
		if ( '' === $name || '' === $value ) {
			continue;
		}
		$property = array(
			'@type' => 'PropertyValue',
			'name'  => $name,
			'value' => $value,
		);
		if (
			isset( $item['unitText'] ) &&
			is_scalar( $item['unitText'] )
		) {
			$unit = barong_k_schema_plain_text( $item['unitText'] );
			if ( '' !== $unit ) {
				$property['unitText'] = $unit;
			}
		}
		$properties[] = $property;
	}
	return $properties;
}

/**
 * Prefer the explicitly supplied sale price, then the regular price.
 *
 * @param WC_Product $product Product or variation being rendered.
 * @return string
 */
function barong_k_schema_price( $product ) {
	$sale    = $product->get_sale_price();
	$regular = $product->get_regular_price();
	$price   = ( '' !== (string) $sale ) ? $sale : $regular;
	if ( '' === (string) $price || ! is_numeric( $price ) ) {
		return '';
	}
	return function_exists( 'wc_format_decimal' )
		? (string) wc_format_decimal( $price )
		: (string) $price;
}

/**
 * Produce a future validity date, using a real scheduled sale end when known.
 *
 * @param WC_Product $product Product or variation being rendered.
 * @return string
 */
function barong_k_schema_price_valid_until( $product ) {
	$now  = function_exists( 'current_time' )
		? (int) current_time( 'timestamp', true )
		: time();
	$sale = $product->get_sale_price();
	if ( '' !== (string) $sale && method_exists( $product, 'get_date_on_sale_to' ) ) {
		$sale_end = $product->get_date_on_sale_to();
		if ( is_object( $sale_end ) && method_exists( $sale_end, 'getTimestamp' ) ) {
			$sale_end_timestamp = (int) $sale_end->getTimestamp();
			if ( $sale_end_timestamp > $now ) {
				return gmdate( 'Y-m-d', $sale_end_timestamp );
			}
		}
	}
	return gmdate( 'Y-m-d', strtotime( '+1 year', $now ) );
}

/**
 * Map Woo stock state to a Schema.org Offer availability URL.
 *
 * @param WC_Product $product Product or variation being rendered.
 * @return string
 */
function barong_k_schema_availability( $product ) {
	$status = method_exists( $product, 'get_stock_status' )
		? (string) $product->get_stock_status()
		: '';
	if ( 'onbackorder' === $status ) {
		return 'https://schema.org/BackOrder';
	}
	if ( 'outofstock' === $status ) {
		return 'https://schema.org/OutOfStock';
	}
	return 'https://schema.org/InStock';
}

/**
 * Fill one Offer with fields required by the Product rich-result contract.
 *
 * @param array<string, mixed> $offer Existing offer data.
 * @param WC_Product          $product Product or variation being rendered.
 * @return array<string, mixed>
 */
function barong_k_schema_offer( $offer, $product ) {
	if ( ! is_array( $offer ) || ! is_a( $product, 'WC_Product' ) ) {
		return $offer;
	}
	$price = barong_k_schema_price( $product );
	if ( '' === $price ) {
		return $offer;
	}
	$currency = function_exists( 'get_woocommerce_currency' )
		? barong_k_schema_plain_text( get_woocommerce_currency() )
		: '';
	if ( '' === $currency ) {
		return $offer;
	}

	$offer['@type']           = isset( $offer['@type'] ) ? $offer['@type'] : 'Offer';
	$offer['price']           = $price;
	$offer['priceCurrency']   = strtoupper( $currency );
	$offer['priceValidUntil'] = barong_k_schema_price_valid_until( $product );
	$offer['availability']    = barong_k_schema_availability( $product );
	$offer['itemCondition']   = 'https://schema.org/NewCondition';
	return $offer;
}

/**
 * Apply Offer enrichment whether the producer emits one object or a list.
 *
 * @param mixed      $offers Existing offer shape.
 * @param WC_Product $product Product being rendered.
 * @return array<string, mixed>|array<int, array<string, mixed>>
 */
function barong_k_schema_offers( $offers, $product ) {
	if ( ! is_array( $offers ) || empty( $offers ) ) {
		return barong_k_schema_offer( array(), $product );
	}
	$is_list = array_keys( $offers ) === range( 0, count( $offers ) - 1 );
	if ( ! $is_list ) {
		return barong_k_schema_offer( $offers, $product );
	}
	foreach ( $offers as $index => $offer ) {
		$offers[ $index ] = barong_k_schema_offer( $offer, $product );
	}
	return $offers;
}

/**
 * Project K-owned fields into either producer's Product graph.
 *
 * @param array<string, mixed> $markup Existing Product schema.
 * @param WC_Product          $product Current product.
 * @return array<string, mixed>
 */
function barong_k_project_product_schema( $markup, $product ) {
	if ( ! is_array( $markup ) || ! is_a( $product, 'WC_Product' ) ) {
		return $markup;
	}

	// Brand is a code-level hard gate, independent of AI-authored product data.
	$markup['brand'] = array(
		'@type' => 'Brand',
		'name'  => 'Barong Yekhna',
	);

	$name = barong_k_schema_name( $product );
	if ( '' !== $name ) {
		$markup['name'] = $name;
	}
	$description = barong_k_schema_description( $product );
	if ( '' !== $description ) {
		$markup['description'] = $description;
	} else {
		unset( $markup['description'] );
	}

	$properties = barong_k_schema_properties( $product );
	if ( $properties ) {
		$markup['additionalProperty'] = $properties;
	} else {
		unset( $markup['additionalProperty'] );
	}
	$markup['offers'] = barong_k_schema_offers(
		isset( $markup['offers'] ) ? $markup['offers'] : array(),
		$product
	);
	return $markup;
}

/** WooCommerce core Product graph adapter. */
function barong_k_woocommerce_product_schema( $markup, $product ) {
	return barong_k_project_product_schema( $markup, $product );
}

/** WooCommerce core Offer adapter. */
function barong_k_woocommerce_offer_schema( $offer, $product ) {
	return barong_k_schema_offer( $offer, $product );
}

/** Yoast WooCommerce SEO Product graph adapter. */
function barong_k_yoast_product_schema( $markup ) {
	$product = barong_k_schema_product();
	return $product
		? barong_k_project_product_schema( $markup, $product )
		: $markup;
}

/** Yoast WooCommerce SEO Offer adapter. */
function barong_k_yoast_offer_schema( $offer, $variation, $product ) {
	$offer_product = barong_k_schema_product( $variation );
	if ( ! $offer_product ) {
		$offer_product = barong_k_schema_product( $product );
	}
	return $offer_product
		? barong_k_schema_offer( $offer, $offer_product )
		: $offer;
}

// Run after producer defaults so the site-owned brand, authored SEO copy,
// supplier-backed properties, and canonical offer cannot be overwritten.
add_filter( 'woocommerce_structured_data_product_offer', 'barong_k_woocommerce_offer_schema', PHP_INT_MAX, 2 );
add_filter( 'woocommerce_structured_data_product', 'barong_k_woocommerce_product_schema', PHP_INT_MAX, 2 );
add_filter( 'wpseo_schema_offer', 'barong_k_yoast_offer_schema', PHP_INT_MAX, 3 );
add_filter( 'wpseo_schema_product', 'barong_k_yoast_product_schema', PHP_INT_MAX, 1 );
