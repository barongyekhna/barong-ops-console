<?php
/**
 * Plugin Name: Barong CS Contact
 * Description: 直连控制台 CS 客服中心的联系表单(瘦插件)。短代码 [barong_contact_form channel="retail|wholesale"];提交经本站 REST 中转转发到控制台,渠道分流 B/C。端点与密钥经 REST 可配(barong_cs_endpoint / barong_cs_key)。
 * Version: 1.0.0
 * Author: Barong Yekhna Console
 */

if ( ! defined( 'ABSPATH' ) ) { exit; }

/** 控制台端点与密钥:REST 可配(与 house-style 同模式,控制台远程管理)。 */
add_action( 'init', function () {
	register_setting( 'options', 'barong_cs_endpoint', array(
		'type' => 'string', 'show_in_rest' => true, 'default' => '',
		'sanitize_callback' => 'esc_url_raw',
	) );
	register_setting( 'options', 'barong_cs_key', array(
		'type' => 'string', 'show_in_rest' => true, 'default' => '',
		'sanitize_callback' => 'sanitize_text_field',
	) );
} );

/** 表单渲染:短代码 [barong_contact_form channel="retail|wholesale"] */
add_shortcode( 'barong_contact_form', function ( $atts ) {
	$atts    = shortcode_atts( array( 'channel' => 'retail' ), $atts );
	$channel = ( 'wholesale' === $atts['channel'] ) ? 'wholesale' : 'retail';
	$uid     = 'bycs-' . wp_generate_password( 6, false, false );
	$is_b2b  = ( 'wholesale' === $channel );

	ob_start(); ?>
<form class="by-cs-form" id="<?php echo esc_attr( $uid ); ?>" data-channel="<?php echo esc_attr( $channel ); ?>" novalidate>
	<div class="by-cs-grid">
		<label class="by-cs-field"><span><?php echo $is_b2b ? 'Company name *' : 'Your name *'; ?></span>
			<input type="text" name="<?php echo $is_b2b ? 'company' : 'name'; ?>" required maxlength="200" autocomplete="<?php echo $is_b2b ? 'organization' : 'name'; ?>">
		</label>
		<?php if ( $is_b2b ) : ?>
		<label class="by-cs-field"><span>Contact person *</span>
			<input type="text" name="name" required maxlength="120" autocomplete="name">
		</label>
		<?php endif; ?>
		<label class="by-cs-field"><span>Email *</span>
			<input type="email" name="email" required maxlength="254" autocomplete="email">
		</label>
		<?php if ( ! $is_b2b ) : ?>
		<label class="by-cs-field"><span>Order number (optional)</span>
			<input type="text" name="order_number" maxlength="64" placeholder="e.g. #3864">
		</label>
		<?php endif; ?>
	</div>
	<label class="by-cs-field"><span><?php echo $is_b2b ? 'Tell us about your requirements *' : 'How can we help? *'; ?></span>
		<textarea name="message" rows="6" required maxlength="5000" placeholder="<?php echo $is_b2b ? 'Product lines, target quantities, destination market…' : 'Tell us what happened, or what you would like to know…'; ?>"></textarea>
	</label>
	<input type="text" name="by_hp" value="" tabindex="-1" autocomplete="off" aria-hidden="true" style="position:absolute;left:-9999px;height:1px;width:1px;opacity:0">
	<div class="by-cs-actions">
		<button type="submit" class="by-cs-submit"><?php echo $is_b2b ? 'Send inquiry' : 'Send message'; ?></button>
		<span class="by-cs-note" aria-live="polite"></span>
	</div>
</form>
<script>
(function(){
	var f=document.getElementById(<?php echo wp_json_encode( $uid ); ?>);
	if(!f) return;
	var t0=Date.now();
	f.addEventListener('submit',function(e){
		e.preventDefault();
		var note=f.querySelector('.by-cs-note'),btn=f.querySelector('.by-cs-submit');
		var data={
			channel:f.getAttribute('data-channel'),
			name:(f.querySelector('[name=name]')||{}).value||'',
			email:(f.querySelector('[name=email]')||{}).value||'',
			company:(f.querySelector('[name=company]')||{}).value||'',
			order_number:(f.querySelector('[name=order_number]')||{}).value||'',
			message:(f.querySelector('[name=message]')||{}).value||'',
			honeypot:(f.querySelector('[name=by_hp]')||{}).value||'',
			form_ms:Date.now()-t0,
			source_url:window.location.href
		};
		if(!data.email||!data.message||!data.name){note.textContent='Please fill in the required fields.';note.className='by-cs-note err';return;}
		btn.disabled=true;note.textContent='Sending…';note.className='by-cs-note';
		fetch('<?php echo esc_url_raw( rest_url( 'barong-cs/v1/submit' ) ); ?>',{
			method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)
		}).then(function(r){return r.json();}).then(function(j){
			if(j&&j.ok){
				f.querySelectorAll('input:not([name=by_hp]),textarea').forEach(function(el){el.value='';});
				note.textContent='Thank you — your message is in. A real person will reply to your email, usually within one business day.';
				note.className='by-cs-note ok';
			}else{
				note.textContent='Something went wrong. Please email us directly at service@barongyekhna.com.';
				note.className='by-cs-note err';
			}
			btn.disabled=false;
		}).catch(function(){
			note.textContent='Something went wrong. Please email us directly at service@barongyekhna.com.';
			note.className='by-cs-note err';btn.disabled=false;
		});
	});
})();
</script>
<?php
	return ob_get_clean();
} );

/** 站内 REST 中转:校验 + 限流 + 转发到控制台(密钥不出服务器)。 */
add_action( 'rest_api_init', function () {
	register_rest_route( 'barong-cs/v1', '/submit', array(
		'methods'             => 'POST',
		'permission_callback' => '__return_true',
		'callback'            => 'by_cs_relay_submit',
	) );
} );

function by_cs_relay_submit( WP_REST_Request $req ) {
	$ip  = isset( $_SERVER['REMOTE_ADDR'] ) ? sanitize_text_field( wp_unslash( $_SERVER['REMOTE_ADDR'] ) ) : '';
	$key = 'by_cs_rl_' . md5( $ip );
	$n   = (int) get_transient( $key );
	if ( $n >= 5 ) {
		return new WP_REST_Response( array( 'ok' => false ), 429 );
	}
	set_transient( $key, $n + 1, MINUTE_IN_SECONDS );

	$endpoint = get_option( 'barong_cs_endpoint', '' );
	$secret   = get_option( 'barong_cs_key', '' );
	if ( ! $endpoint || ! $secret ) {
		return new WP_REST_Response( array( 'ok' => false, 'error' => 'not_configured' ), 503 );
	}

	$channel = ( 'wholesale' === $req->get_param( 'channel' ) ) ? 'wholesale' : 'retail';
	$payload = array(
		'channel'      => $channel,
		'name'         => mb_substr( sanitize_text_field( (string) $req->get_param( 'name' ) ), 0, 120 ),
		'email'        => sanitize_email( (string) $req->get_param( 'email' ) ),
		'company'      => mb_substr( sanitize_text_field( (string) $req->get_param( 'company' ) ), 0, 200 ),
		'order_number' => mb_substr( sanitize_text_field( (string) $req->get_param( 'order_number' ) ), 0, 64 ),
		'message'      => mb_substr( sanitize_textarea_field( (string) $req->get_param( 'message' ) ), 0, 5000 ),
		'source_url'   => esc_url_raw( (string) $req->get_param( 'source_url' ) ),
		'honeypot'     => (string) $req->get_param( 'honeypot' ),
		'form_ms'      => (int) $req->get_param( 'form_ms' ),
	);
	if ( ! is_email( $payload['email'] ) || '' === $payload['message'] || '' === $payload['name'] ) {
		return new WP_REST_Response( array( 'ok' => false ), 422 );
	}

	$resp = wp_remote_post( $endpoint, array(
		'timeout' => 12,
		'headers' => array(
			'Content-Type'            => 'application/json',
			'X-BY-CS-KEY'             => $secret,
			'X-Forwarded-For-Origin'  => $ip,
			'User-Agent'              => 'BarongCS-Relay/1.0',
		),
		'body'    => wp_json_encode( array_merge( $payload, array(
			'user_agent' => isset( $_SERVER['HTTP_USER_AGENT'] ) ? mb_substr( sanitize_text_field( wp_unslash( $_SERVER['HTTP_USER_AGENT'] ) ), 0, 300 ) : '',
		) ) ),
	) );
	if ( is_wp_error( $resp ) ) {
		return new WP_REST_Response( array( 'ok' => false ), 502 );
	}
	$code = (int) wp_remote_retrieve_response_code( $resp );
	if ( $code >= 200 && $code < 300 ) {
		return new WP_REST_Response( array( 'ok' => true ), 200 );
	}
	return new WP_REST_Response( array( 'ok' => false ), 502 );
}
