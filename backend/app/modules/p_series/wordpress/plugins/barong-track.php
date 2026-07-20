<?php
/**
 * Plugin Name: Barong Track
 * Description: 买家自助物流查询(瘦插件)。短代码 [barong_track]:已登录买家自动列出本人订单并就地展开物流时间线;游客走「订单号 + 邮箱」查询。身份与订单归属由 WordPress 判定,轨迹向控制台按订单号查询(端点/密钥经 REST 配置:barong_track_endpoint / barong_track_key)。
 * Version: 1.0.0
 * Author: Barong Yekhna Console
 */

if ( ! defined( 'ABSPATH' ) ) { exit; }

const BY_TRACK_VERSION   = '1.0.0';
const BY_TRACK_MAX_ORDERS = 20;
const BY_TRACK_CACHE_TTL  = 180;

/** 端点与密钥:REST 可配(与 house-style / cs-contact 同模式,控制台远程管理)。 */
add_action( 'init', function () {
	register_setting( 'options', 'barong_track_endpoint', array(
		'type' => 'string', 'show_in_rest' => true, 'default' => '',
		'sanitize_callback' => 'esc_url_raw',
	) );
	register_setting( 'options', 'barong_track_key', array(
		'type' => 'string', 'show_in_rest' => true, 'default' => '',
		'sanitize_callback' => 'sanitize_text_field',
	) );
} );

/**
 * 向控制台按订单号查轨迹。
 * fail-safe 铁律:控制台不可用时返回空数组,页面照常渲染订单(只是没有轨迹),
 * 绝不让一个下游故障把买家的订单页整个打掉。
 */
function by_track_lookup( array $order_numbers ) {
	$order_numbers = array_values( array_unique( array_filter( array_map( 'strval', $order_numbers ) ) ) );
	if ( ! $order_numbers ) { return array(); }
	$order_numbers = array_slice( $order_numbers, 0, BY_TRACK_MAX_ORDERS );

	$endpoint = (string) get_option( 'barong_track_endpoint', '' );
	$key      = (string) get_option( 'barong_track_key', '' );
	if ( '' === $endpoint || '' === $key ) { return array(); }

	$cache_key = 'by_track_' . md5( $endpoint . '|' . implode( ',', $order_numbers ) );
	$cached    = get_transient( $cache_key );
	if ( is_array( $cached ) ) { return $cached; }

	$resp = wp_remote_post( $endpoint, array(
		'timeout' => 6,
		'headers' => array(
			'Content-Type'    => 'application/json',
			'X-BY-TRACK-KEY'  => $key,
			'User-Agent'      => 'BarongTrack/' . BY_TRACK_VERSION,
		),
		'body'    => wp_json_encode( array( 'order_numbers' => $order_numbers ) ),
	) );
	if ( is_wp_error( $resp ) ) { return array(); }
	$code = (int) wp_remote_retrieve_response_code( $resp );
	if ( $code < 200 || $code >= 300 ) { return array(); }

	$data = json_decode( (string) wp_remote_retrieve_body( $resp ), true );
	$out  = array();
	if ( is_array( $data ) && isset( $data['results'] ) && is_array( $data['results'] ) ) {
		foreach ( $data['results'] as $row ) {
			if ( is_array( $row ) && isset( $row['order_number'] ) ) {
				$out[ (string) $row['order_number'] ] = $row;
			}
		}
	}
	set_transient( $cache_key, $out, BY_TRACK_CACHE_TTL );
	return $out;
}

/** 状态 → 买家看得懂的文案。 */
function by_track_status_label( $status ) {
	$map = array(
		'info_received'    => 'Label created',
		'in_transit'       => 'In transit',
		'out_for_delivery' => 'Out for delivery',
		'delivered'        => 'Delivered',
		'exception'        => 'Needs attention',
		'expired'          => 'No recent updates',
		'not_found'        => 'Awaiting carrier scan',
	);
	$status = (string) $status;
	return isset( $map[ $status ] ) ? $map[ $status ] : 'Tracking';
}

function by_track_status_tone( $status ) {
	if ( 'delivered' === $status ) { return 'ok'; }
	if ( 'exception' === $status ) { return 'warn'; }
	return 'live';
}

/** 事件时间 → 买家可读(失败则原样返回,绝不吞掉信息)。 */
function by_track_time( $raw ) {
	$raw = trim( (string) $raw );
	if ( '' === $raw ) { return ''; }
	$ts = strtotime( $raw );
	if ( ! $ts ) { return $raw; }
	return date_i18n( 'M j, Y · H:i', $ts );
}

/** 单条轨迹时间线。 */
function by_track_render_trail( array $record ) {
	$events = isset( $record['events'] ) && is_array( $record['events'] ) ? $record['events'] : array();
	if ( ! $events ) {
		return '<p class="by-track-empty">No carrier scans yet. Tracking usually appears within 24–48 hours of dispatch.</p>';
	}
	$html = '<ol class="by-track-trail">';
	$first = true;
	foreach ( $events as $event ) {
		if ( ! is_array( $event ) ) { continue; }
		$time = by_track_time( isset( $event['time'] ) ? $event['time'] : '' );
		$loc  = trim( (string) ( isset( $event['location'] ) ? $event['location'] : '' ) );
		$desc = trim( (string) ( isset( $event['description'] ) ? $event['description'] : '' ) );
		$html .= '<li class="by-track-event' . ( $first ? ' is-latest' : '' ) . '">';
		$html .= '<span class="by-track-dot" aria-hidden="true"></span>';
		$html .= '<span class="by-track-desc">' . esc_html( $desc !== '' ? $desc : 'Update' ) . '</span>';
		$meta = array_filter( array( $loc, $time ) );
		if ( $meta ) {
			$html .= '<span class="by-track-meta">' . esc_html( implode( ' · ', $meta ) ) . '</span>';
		}
		$html .= '</li>';
		$first = false;
	}
	return $html . '</ol>';
}

/** 订单卡片(共用于登录态与游客态)。 */
function by_track_render_order_card( $order, array $record ) {
	$number = $order->get_order_number();
	$state  = isset( $record['state'] ) ? (string) $record['state'] : 'unknown';

	$items = array();
	foreach ( $order->get_items() as $item ) {
		$items[] = $item->get_name() . ' × ' . $item->get_quantity();
		if ( count( $items ) >= 3 ) { break; }
	}
	$item_line = implode( ', ', $items );
	if ( count( $order->get_items() ) > 3 ) { $item_line .= ' …'; }

	$html  = '<article class="by-track-card">';
	$html .= '<header class="by-track-card-head">';
	$html .= '<div><p class="by-track-num">Order #' . esc_html( $number ) . '</p>';
	$html .= '<p class="by-track-sub">' . esc_html( wc_format_datetime( $order->get_date_created(), 'M j, Y' ) )
		. ' · ' . esc_html( wc_get_order_status_name( $order->get_status() ) ) . '</p></div>';

	if ( 'tracked' === $state ) {
		$tone = by_track_status_tone( isset( $record['tracking_status'] ) ? $record['tracking_status'] : '' );
		$html .= '<span class="by-track-badge ' . esc_attr( $tone ) . '">'
			. esc_html( by_track_status_label( isset( $record['tracking_status'] ) ? $record['tracking_status'] : '' ) )
			. '</span>';
	} elseif ( 'not_shipped' === $state ) {
		$html .= '<span class="by-track-badge prep">Preparing</span>';
	}
	$html .= '</header>';

	if ( '' !== $item_line ) {
		$html .= '<p class="by-track-items">' . esc_html( $item_line ) . '</p>';
	}

	if ( 'tracked' === $state ) {
		$num = trim( (string) ( isset( $record['tracking_number'] ) ? $record['tracking_number'] : '' ) );
		$html .= '<details class="by-track-details"><summary>View tracking</summary>';
		if ( '' !== $num ) {
			$html .= '<p class="by-track-number">Tracking number <strong>' . esc_html( $num ) . '</strong></p>';
		}
		$html .= by_track_render_trail( $record );
		$html .= '</details>';
	} elseif ( 'not_shipped' === $state ) {
		$html .= '<p class="by-track-empty">This order is being prepared. Tracking appears here as soon as it ships.</p>';
	} else {
		$html .= '<p class="by-track-empty">No tracking information yet. If this order shipped a while ago, '
			. '<a href="' . esc_url( home_url( '/contact/' ) ) . '">contact us</a> and we will look into it.</p>';
	}

	return $html . '</article>';
}

/** 登录态:服务端直接算出"这个人有哪些订单",浏览器无从指定订单号。 */
function by_track_render_account() {
	$user_id = get_current_user_id();
	$orders  = wc_get_orders( array(
		'customer_id' => $user_id,
		'limit'       => BY_TRACK_MAX_ORDERS,
		'orderby'     => 'date',
		'order'       => 'DESC',
	) );
	if ( ! $orders ) {
		return '<div class="by-track"><p class="by-track-empty">You have no orders yet. '
			. '<a href="' . esc_url( home_url( '/shop-2/' ) ) . '">Browse the collection</a>.</p></div>';
	}

	$numbers = array();
	foreach ( $orders as $order ) { $numbers[] = (string) $order->get_order_number(); }
	$records = by_track_lookup( $numbers );

	$html = '<div class="by-track">';
	foreach ( $orders as $order ) {
		$key = (string) $order->get_order_number();
		$html .= by_track_render_order_card( $order, isset( $records[ $key ] ) ? $records[ $key ] : array() );
	}
	return $html . '</div>';
}

/** 游客态:订单号 + 下单邮箱必须同时对上(与 Woo 原生查询同等强度)。 */
function by_track_render_guest() {
	$notice = '';
	$result = '';

	$submitted = isset( $_POST['by_track_submit'] );
	if ( $submitted && isset( $_POST['by_track_nonce'] )
		&& wp_verify_nonce( sanitize_text_field( wp_unslash( $_POST['by_track_nonce'] ) ), 'by_track_guest' ) ) {

		$ip  = isset( $_SERVER['REMOTE_ADDR'] ) ? sanitize_text_field( wp_unslash( $_SERVER['REMOTE_ADDR'] ) ) : '';
		$rl  = 'by_track_rl_' . md5( $ip );
		$hit = (int) get_transient( $rl );
		if ( $hit >= 8 ) {
			$notice = '<p class="by-track-note err">Too many lookups. Please wait a minute and try again.</p>';
		} else {
			set_transient( $rl, $hit + 1, MINUTE_IN_SECONDS );

			$raw_number = trim( sanitize_text_field( wp_unslash( isset( $_POST['by_track_order'] ) ? $_POST['by_track_order'] : '' ) ) );
			$email      = sanitize_email( wp_unslash( isset( $_POST['by_track_email'] ) ? $_POST['by_track_email'] : '' ) );
			$number     = ltrim( $raw_number, '#' );

			$order = null;
			if ( '' !== $number && is_email( $email ) ) {
				$maybe = wc_get_order( absint( $number ) );
				// 号码可能是 order_number 而非 post id;两者都试,但最终一律以邮箱比对为准。
				if ( ! $maybe ) {
					$found = wc_get_orders( array( 'limit' => 1, 'search' => $number ) );
					$maybe = $found ? $found[0] : null;
				}
				if ( $maybe && (string) $maybe->get_order_number() === (string) $number
					&& strtolower( $maybe->get_billing_email() ) === strtolower( $email ) ) {
					$order = $maybe;
				}
			}

			if ( $order ) {
				$records = by_track_lookup( array( (string) $order->get_order_number() ) );
				$key     = (string) $order->get_order_number();
				$result  = '<div class="by-track">'
					. by_track_render_order_card( $order, isset( $records[ $key ] ) ? $records[ $key ] : array() )
					. '</div>';
			} else {
				// 统一措辞:不透露"这个订单号存在但邮箱不对",避免成为订单号探测器。
				$notice = '<p class="by-track-note err">We could not find an order with that number and email. '
					. 'Please check both and try again.</p>';
			}
		}
	}

	$login = wc_get_page_permalink( 'myaccount' );
	$html  = '<div class="by-track-guest">';
	$html .= '<div class="by-track-signin"><p><strong>Have an account?</strong> '
		. '<a href="' . esc_url( $login ? $login : home_url( '/my-account/' ) ) . '">Sign in</a> '
		. 'and every order you have placed appears here automatically — no numbers to type.</p></div>';
	$html .= $notice . $result;
	$html .= '<form class="by-track-form" method="post">';
	$html .= wp_nonce_field( 'by_track_guest', 'by_track_nonce', true, false );
	$html .= '<div class="by-track-grid">';
	$html .= '<label class="by-track-field"><span>Order number</span>'
		. '<input type="text" name="by_track_order" maxlength="64" placeholder="e.g. 3864" required '
		. 'value="' . esc_attr( isset( $_POST['by_track_order'] ) ? sanitize_text_field( wp_unslash( $_POST['by_track_order'] ) ) : '' ) . '"></label>';
	$html .= '<label class="by-track-field"><span>Email used at checkout</span>'
		. '<input type="email" name="by_track_email" maxlength="254" required '
		. 'value="' . esc_attr( isset( $_POST['by_track_email'] ) ? sanitize_email( wp_unslash( $_POST['by_track_email'] ) ) : '' ) . '"></label>';
	$html .= '</div>';
	$html .= '<button type="submit" name="by_track_submit" value="1" class="by-track-submit">Track my order</button>';
	$html .= '</form></div>';
	return $html;
}

add_shortcode( 'barong_track', function () {
	if ( ! function_exists( 'wc_get_orders' ) ) {
		return '<p class="by-track-empty">Order tracking is temporarily unavailable.</p>';
	}
	return is_user_logged_in() ? by_track_render_account() : by_track_render_guest();
} );

/** 诊断:配置与连通性(密钥保护,与 CS 共用 barong_cs_key)。 */
add_action( 'template_redirect', function () {
	if ( ! isset( $_GET['by-track-ping'] ) ) { return; }
	$secret = (string) get_option( 'barong_cs_key', '' );
	$given  = sanitize_text_field( wp_unslash( $_GET['by-track-ping'] ) );
	header( 'Content-Type: application/json; charset=UTF-8' );
	if ( '' === $secret || ! hash_equals( $secret, $given ) ) {
		echo wp_json_encode( array( 'ok' => false ) );
		exit;
	}
	echo wp_json_encode( array(
		'ok'            => true,
		'version'       => BY_TRACK_VERSION,
		'endpoint_set'  => '' !== (string) get_option( 'barong_track_endpoint', '' ),
		'key_set'       => '' !== (string) get_option( 'barong_track_key', '' ),
		'woo'           => function_exists( 'wc_get_orders' ),
	) );
	exit;
}, 0 );
