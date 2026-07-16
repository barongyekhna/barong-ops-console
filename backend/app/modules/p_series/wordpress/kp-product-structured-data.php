<?php
/**
 * Plugin Name: Barong K Product Structured Data
 * Description: Adds supplier-verified K specs to Woo Product JSON-LD.
 * Version: 1.0.0
 *
 * Deploy as a WordPress must-use plugin. The P upload workflow stores a JSON
 * list of PropertyValue objects in `_kp_additional_property`; this filter
 * validates the list again before adding it to WooCommerce's Product graph.
 */

defined( 'ABSPATH' ) || exit;

/**
 * @param array<string, mixed> $markup  WooCommerce Product structured data.
 * @param WC_Product          $product Current product.
 * @return array<string, mixed>
 */
function barong_k_product_structured_data( $markup, $product ) {
	if ( ! is_array( $markup ) || ! is_a( $product, 'WC_Product' ) ) {
		return $markup;
	}

	// Brand is a code-level hard gate, independent of AI/authored product data.
	$markup['brand'] = array(
		'@type' => 'Brand',
		'name'  => 'Barong Yekhna',
	);

	$raw = $product->get_meta( '_kp_additional_property', true );
	if ( ! is_string( $raw ) || '' === trim( $raw ) ) {
		return $markup;
	}
	$decoded = json_decode( $raw, true );
	if ( ! is_array( $decoded ) ) {
		return $markup;
	}

	$properties = array();
	foreach ( array_slice( $decoded, 0, 100 ) as $item ) {
		if ( ! is_array( $item ) ) {
			continue;
		}
		if (
			! isset( $item['name'], $item['value'] ) ||
			! is_scalar( $item['name'] ) ||
			! is_scalar( $item['value'] )
		) {
			continue;
		}
		$name  = isset( $item['name'] ) ? sanitize_text_field( $item['name'] ) : '';
		$value = isset( $item['value'] ) ? sanitize_text_field( $item['value'] ) : '';
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
			is_scalar( $item['unitText'] ) &&
			'' !== trim( (string) $item['unitText'] )
		) {
			$property['unitText'] = sanitize_text_field( $item['unitText'] );
		}
		$properties[] = $property;
	}
	if ( $properties ) {
		$markup['additionalProperty'] = $properties;
	}

	// Do not set aggregateRating/review here. Woo core adds them only when the
	// product has real stored ratings and approved review comments.
	return $markup;
}
// Run at the last practical priority so later theme/plugin defaults cannot
// replace the site-owned brand or the verified property projection.
add_filter( 'woocommerce_structured_data_product', 'barong_k_product_structured_data', PHP_INT_MAX, 2 );
