<?php
/**
 * Plugin Name: Barong B2B Widget
 * Description: 产品页上的批发浮窗（Buying for a store?）。每产品数据来自控制台写入的 _kp_b2b meta，站点级政策文案来自 barong_b2b_policy option，两者都由控制台远程管理——本文件永不需要重新上传。
 * Version: 1.4.0
 * Author: Barong Yekhna
 *
 * 为什么存在：零售买家逛产品页时看不出这货能批发。一个开店的人看到「Buying
 * for a store?」是热线索——他已经站在店里了，转化率比冷开发高一个数量级。
 *
 * 三条红线（都是业务约束，不是样式偏好）：
 *
 * 1. **绝不显示批发价。** GMC 会把「页面价与 feed 价不符」判成 Misrepresentation，
 *    这个账号已经因此被封过两次，只剩一次申诉机会。契约层就没有价格字段。
 *    藏起价格还有第二个好处：批发价不外泄，零售商不会发现你的成本，
 *    渠道冲突从源头就没了。
 * 2. **绝不进任何 schema.org 标记。** 爬虫只应读到零售那一套结构化数据。
 *    免运费那句必须带 "Wholesale" 字样，和零售的「满 $100 免运费」区分开。
 * 3. **meta 为空就什么都不渲染。** 控制台清空批发信息时会把 _kp_b2b 写成空串
 *    （不是删除），浮窗随即消失，绝不留下点进去没内容的死链。
 *
 * v1.1.0：改成浮层（原来内联展开会把产品页撑得很长）、触发按钮做醒目、
 * 邮箱和 WhatsApp 各占一行（原来挤在同一行且号码折行）。
 *
 * v1.2.0：触发器从整宽深色大块改成**单行文字链**。两个原因：
 * ① 它挂在 woocommerce_single_product_summary（**右栏**），64px 的高度
 *    全加在右边，左边图片下面就空出一块；缩到 ~24px 后两栏基本齐平。
 * ② **产品页上最该抢眼的是 Add to Cart**。深色满宽块比真正的购买按钮
 *    还抢戏，会伤零售转化。批发入口的定位是「找的人找得到，不找的人
 *    不打扰」——靠位置抓人，不靠尺寸。丰富内容留在浮层里，那是免费版面。
 *
 * v1.3.0：浮层底部加一条回 /wholesale/ 的链接，把内链网闭合——产品页浮窗
 * 只接住已经点进某个产品的人，主阵地才是店家搜供应商时真正会落到的地方。
 *
 * v1.3.1：programme → program。**站是给美国买家看的，一律美式拼写**——
 * programme/centre/catalogue 都是英联邦拼法，美国零售商看到会觉得别扭。
 * 同理见记忆里的「美国市场用英制单位」，是同一类错误。
 *
 * v1.4.0：给 GEO 指南文章末尾加一行回批发页的链接，把内链网闭合。
 * 走站点 option（barong_b2b_guide_links：WP 类目 term id → 批发页），
 * **零 GEO 代码改动**——不碰另一个会话正在改的内容生成模块，也不用
 * 逐篇 PUT 文章。以后 GEO 发新指南，只要类目对得上就自动带上这行。
 *
 * ⚠️ 指南文章只挂**叶子类目**（实测 categories: [1501]，不带祖先），
 * 所以 in_category(祖先) 是 false。必须拿文章实际的 term 列表来查表。
 *
 * 前台专用：admin / REST / cron 一律跳过，让 GMC 导出和 REST 读到的是零售真相。
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

const BY_B2B_VERSION       = '1.4.0';
const BY_B2B_META_KEY      = '_kp_b2b';
const BY_B2B_POLICY_OPTION = 'barong_b2b_policy';
// WP 类目 term id → 批发页。控制台生成批发页时一并写入。
const BY_B2B_GUIDE_OPTION  = 'barong_b2b_guide_links';

/**
 * 站点级政策文案走 option，由控制台一次 REST 写入，全站产品立刻生效。
 * 每产品数据走 meta（n8n 逐个写）。这样政策一改不用重推任何产品。
 */
function by_b2b_register_setting() {
	register_setting(
		'options',
		BY_B2B_POLICY_OPTION,
		array(
			'type'              => 'string',
			'description'       => 'JSON: B2B 浮窗的站点级文案与政策（控制台管理）。',
			'default'           => '',
			'show_in_rest'      => true,
			'sanitize_callback' => 'by_b2b_sanitize_policy',
		)
	);
	register_setting(
		'options',
		BY_B2B_GUIDE_OPTION,
		array(
			'type'              => 'string',
			'description'       => 'JSON: WP 类目 → 批发页（控制台管理）。',
			'default'           => '',
			'show_in_rest'      => true,
			'sanitize_callback' => 'by_b2b_sanitize_policy',
		)
	);
}
add_action( 'init', 'by_b2b_register_setting' );

/** 读类目 → 批发页映射；坏数据一律当没有。 */
function by_b2b_guide_links() {
	$raw = get_option( BY_B2B_GUIDE_OPTION, '' );
	if ( ! is_string( $raw ) || '' === trim( $raw ) ) {
		return array();
	}
	$decoded = json_decode( $raw, true );
	return is_array( $decoded ) ? $decoded : array();
}

/**
 * 指南文章末尾的回链。
 *
 * static $done 防重入：the_content 在一个请求里会被多次触发（摘要、
 * 相关文章、SEO 插件都会调），不加闩会渲染出好几行。
 */
function by_b2b_guide_backlink( $content ) {
	static $done = false;
	if ( $done || ! by_b2b_should_render() ) {
		return $content;
	}
	if ( ! is_singular( 'post' ) || ! in_the_loop() || ! is_main_query() ) {
		return $content;
	}
	$map = by_b2b_guide_links();
	if ( empty( $map ) ) {
		return $content;
	}
	// 只看文章**实际挂的** term id——指南只带叶子类目，不能推祖先。
	$terms = get_the_category();
	if ( ! is_array( $terms ) ) {
		return $content;
	}
	foreach ( $terms as $term ) {
		$key = (string) ( isset( $term->term_id ) ? $term->term_id : '' );
		if ( '' === $key || ! isset( $map[ $key ] ) ) {
			continue;
		}
		$entry = $map[ $key ];
		$url   = isset( $entry['url'] ) ? esc_url( $entry['url'] ) : '';
		if ( '' === $url ) {
			continue;
		}
		$done = true;
		return $content
			. '<p class="by-b2b-guide-cta"><a href="' . $url . '">'
			. '&#127978; Buying for a store? See our wholesale program &rarr;'
			. '</a></p>';
	}
	return $content;
}
add_filter( 'the_content', 'by_b2b_guide_backlink', 20 );


/**
 * 存进来的必须是能解析的 JSON 对象，否则一律存空——宁可不显示，
 * 也不能把半截垃圾渲染到产品页上。
 */
function by_b2b_sanitize_policy( $value ) {
	$raw = is_string( $value ) ? trim( $value ) : '';
	if ( '' === $raw ) {
		return '';
	}
	$decoded = json_decode( $raw, true );
	if ( ! is_array( $decoded ) ) {
		return '';
	}
	return wp_json_encode( $decoded );
}

/** 读站点级政策；坏数据一律当没有。 */
function by_b2b_policy() {
	$raw = get_option( BY_B2B_POLICY_OPTION, '' );
	if ( ! is_string( $raw ) || '' === trim( $raw ) ) {
		return array();
	}
	$decoded = json_decode( $raw, true );
	return is_array( $decoded ) ? $decoded : array();
}

/** 读某产品的批发数据；空串/坏数据一律当没有。 */
function by_b2b_product_data( $product ) {
	if ( ! is_object( $product ) || ! method_exists( $product, 'get_meta' ) ) {
		return array();
	}
	$raw = $product->get_meta( BY_B2B_META_KEY, true );
	if ( ! is_string( $raw ) || '' === trim( $raw ) ) {
		return array();
	}
	$decoded = json_decode( $raw, true );
	return is_array( $decoded ) ? $decoded : array();
}

/** 前台守卫：admin / REST / cron / feed 一律不渲染。 */
function by_b2b_should_render() {
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
	return true;
}

/** WhatsApp 深链只认纯数字。 */
function by_b2b_wa_link( $number ) {
	$digits = preg_replace( '/\D+/', '', (string) $number );
	return $digits ? 'https://wa.me/' . $digits : '';
}

/**
 * 样式只输出一次。刻意内联：这个浮层要在任何主题下都长得一样，
 * 不依赖 house-style 那个 CSS 注入器，也不多发一个 HTTP 请求。
 */
function by_b2b_styles_once() {
	static $printed = false;
	if ( $printed ) {
		return;
	}
	$printed = true;
	?>
	<style id="by-b2b-css">
	.by-b2b{margin:12px 0}
	/* 单行文字链：不跟 Add to Cart 抢戏，也几乎不占右栏高度。 */
	.by-b2b-open{display:inline-flex;align-items:center;gap:7px;
		padding:5px 0;border:0;border-bottom:1px solid rgba(43,64,85,.22);
		background:none;color:#2b4055;font-size:13.5px;font-weight:600;
		line-height:1.4;cursor:pointer;text-align:left;
		transition:color .15s ease,border-color .15s ease}
	.by-b2b-open:hover{color:#12253a;border-bottom-color:rgba(43,64,85,.6)}
	.by-b2b-open .by-b2b-mark{font-size:15px;line-height:1}
	.by-b2b-open .by-b2b-hint{font-weight:400;color:#6b7a8b}
	.by-b2b-open .by-b2b-arrow{opacity:.6;font-weight:400}
	/* 窄屏把提示藏掉，保证永远只有一行。 */
	@media (max-width:480px){.by-b2b-open .by-b2b-hint{display:none}}

	.by-b2b-modal[hidden]{display:none}
	.by-b2b-modal{position:fixed;inset:0;z-index:99999;display:flex;
		align-items:center;justify-content:center;padding:20px}
	.by-b2b-backdrop{position:absolute;inset:0;background:rgba(12,18,26,.62)}
	.by-b2b-card{position:relative;z-index:1;width:100%;max-width:460px;
		max-height:88vh;overflow-y:auto;padding:26px 26px 22px;
		border-radius:14px;background:#fff;color:#1d2b3a;
		box-shadow:0 24px 60px rgba(0,0,0,.34);text-align:left}
	.by-b2b-close{position:absolute;top:10px;right:12px;width:34px;height:34px;
		border:0;background:none;font-size:26px;line-height:1;cursor:pointer;
		color:#7d8a99}
	.by-b2b-close:hover{color:#1d2b3a}
	.by-b2b-card h3{margin:0 0 6px;font-size:19px;line-height:1.3}
	.by-b2b-sub{margin:0 0 14px;font-size:13.5px;color:#5a6675;line-height:1.5}
	.by-b2b-facts{margin:0 0 6px;padding:10px 12px;border-radius:8px;
		background:#f2f5f8;font-size:13.5px;font-weight:600}
	.by-b2b-variants{margin:0 0 14px;font-size:13px;color:#5a6675}
	.by-b2b-policies{margin:0 0 18px;padding:0;list-style:none}
	.by-b2b-policies li{position:relative;padding:0 0 0 22px;margin-bottom:7px;
		font-size:13.5px;line-height:1.5}
	.by-b2b-policies li:before{content:"\2713";position:absolute;left:0;top:0;
		color:#1f9d63;font-weight:700}
	.by-b2b-form{margin-bottom:16px}
	/* 回主阵地：浮窗只接住已经在看某个产品的人，全站入口在 /wholesale/。 */
	.by-b2b-more{margin:0 0 14px;font-size:13px}
	.by-b2b-more a{color:#2b6cb0;text-decoration:none}
	.by-b2b-more a:hover{text-decoration:underline}

	/* 邮箱和 WhatsApp 各占一行——原来挤在同一行，号码还折了行。 */
	.by-b2b-contact{display:flex;flex-direction:column;gap:8px;
		padding-top:14px;border-top:1px solid #e3e8ee}
	.by-b2b-contact a{display:flex;align-items:center;gap:8px;
		font-size:13.5px;color:#1d2b3a;text-decoration:none;word-break:break-all}
	.by-b2b-contact a:hover{text-decoration:underline}
	.by-b2b-contact .by-b2b-ico{flex:0 0 auto;font-size:15px}
	@media (max-width:480px){
		.by-b2b-card{padding:22px 18px 18px;max-height:92vh}
	}
	</style>
	<?php
}

/**
 * 产品页浮窗。
 *
 * static $busy 防重入：主题或别的插件可能在一个页面里多次触发 summary 钩子，
 * 重复渲染过一次结构化数据块之后全站 502（cat-thumb 和 k-structured-data
 * 都为此加过闩）。
 */
function by_b2b_render_widget() {
	static $busy = false;
	if ( $busy || ! by_b2b_should_render() ) {
		return;
	}

	global $product;
	$data = by_b2b_product_data( $product );
	if ( empty( $data ) ) {
		return; // 控制台撤下了：什么都不渲染。
	}

	$policy = by_b2b_policy();
	$busy   = true;

	$moq       = isset( $data['moq'] ) ? absint( $data['moq'] ) : 0;
	$case_pack = isset( $data['case_pack'] ) ? absint( $data['case_pack'] ) : 0;
	$lead_days = isset( $data['lead_days'] ) ? absint( $data['lead_days'] ) : 0;
	$variants  = isset( $data['variants'] ) && is_string( $data['variants'] )
		? sanitize_text_field( $data['variants'] )
		: '';

	$headline = isset( $policy['headline'] ) ? sanitize_text_field( $policy['headline'] ) : 'Buying for a store?';
	$subline  = isset( $policy['subline'] ) ? sanitize_text_field( $policy['subline'] ) : '';
	$cta      = isset( $policy['cta'] ) ? sanitize_text_field( $policy['cta'] ) : 'Request wholesale pricing';
	$email    = isset( $policy['email'] ) ? sanitize_email( $policy['email'] ) : '';
	$whatsapp = isset( $policy['whatsapp'] ) ? sanitize_text_field( $policy['whatsapp'] ) : '';
	$bullets  = ( isset( $policy['policies'] ) && is_array( $policy['policies'] ) )
		? array_slice( $policy['policies'], 0, 6 )
		: array();

	$sku = ( is_object( $product ) && method_exists( $product, 'get_sku' ) )
		? (string) $product->get_sku()
		: '';

	$facts = array();
	if ( $moq ) {
		$facts[] = sprintf( 'MOQ %d', $moq );
	}
	if ( $case_pack ) {
		$facts[] = sprintf( 'Case pack %d', $case_pack );
	}
	if ( $lead_days ) {
		$facts[] = sprintf( '%d days lead time', $lead_days );
	}

	by_b2b_styles_once();
	$uid = 'by-b2b-' . ( $sku ? sanitize_html_class( $sku ) : 'w' );
	?>
	<div class="by-b2b" data-sku="<?php echo esc_attr( $sku ); ?>">
		<button type="button" class="by-b2b-open" aria-haspopup="dialog">
			<span class="by-b2b-mark" aria-hidden="true">&#127978;</span>
			<span><?php echo esc_html( $headline ); ?></span>
			<?php if ( $moq ) : ?>
				<span class="by-b2b-hint">MOQ <?php echo absint( $moq ); ?></span>
			<?php endif; ?>
			<span class="by-b2b-arrow" aria-hidden="true">&rarr;</span>
		</button>

		<div class="by-b2b-modal" hidden role="dialog" aria-modal="true"
			aria-labelledby="<?php echo esc_attr( $uid ); ?>-title">
			<div class="by-b2b-backdrop" data-by-b2b-dismiss></div>
			<div class="by-b2b-card">
				<button type="button" class="by-b2b-close" data-by-b2b-dismiss
					aria-label="Close">&times;</button>

				<h3 id="<?php echo esc_attr( $uid ); ?>-title"><?php echo esc_html( $headline ); ?></h3>
				<?php if ( '' !== $subline ) : ?>
					<p class="by-b2b-sub"><?php echo esc_html( $subline ); ?></p>
				<?php endif; ?>

				<?php if ( ! empty( $facts ) ) : ?>
					<p class="by-b2b-facts"><?php echo esc_html( implode( '  ·  ', $facts ) ); ?></p>
				<?php endif; ?>
				<?php if ( '' !== $variants ) : ?>
					<p class="by-b2b-variants"><?php echo esc_html( $variants ); ?></p>
				<?php endif; ?>

				<?php if ( ! empty( $bullets ) ) : ?>
					<ul class="by-b2b-policies">
						<?php foreach ( $bullets as $bullet ) : ?>
							<?php if ( is_string( $bullet ) && '' !== trim( $bullet ) ) : ?>
								<li><?php echo esc_html( sanitize_text_field( $bullet ) ); ?></li>
							<?php endif; ?>
						<?php endforeach; ?>
					</ul>
				<?php endif; ?>

				<?php if ( shortcode_exists( 'barong_contact_form' ) ) : ?>
					<div class="by-b2b-form">
						<?php echo do_shortcode( '[barong_contact_form channel="wholesale" sku="' . esc_attr( $sku ) . '"]' ); ?>
					</div>
				<?php elseif ( '' !== $email ) : ?>
					<p class="by-b2b-form">
						<a href="<?php echo esc_url( 'mailto:' . $email . '?subject=' . rawurlencode( 'Wholesale enquiry - ' . $sku ) ); ?>">
							<?php echo esc_html( $cta ); ?>
						</a>
					</p>
				<?php endif; ?>

				<p class="by-b2b-more">
					<a href="/wholesale/">See our full wholesale program &rarr;</a>
				</p>

				<div class="by-b2b-contact">
					<?php if ( '' !== $email ) : ?>
						<a href="<?php echo esc_url( 'mailto:' . $email ); ?>">
							<span class="by-b2b-ico" aria-hidden="true">&#9993;</span>
							<span><?php echo esc_html( $email ); ?></span>
						</a>
					<?php endif; ?>
					<?php if ( '' !== $whatsapp ) : ?>
						<?php $wa = by_b2b_wa_link( $whatsapp ); ?>
						<a<?php echo $wa ? ' href="' . esc_url( $wa ) . '" rel="noopener" target="_blank"' : ''; ?>>
							<span class="by-b2b-ico" aria-hidden="true">&#128172;</span>
							<span>WhatsApp <?php echo esc_html( $whatsapp ); ?></span>
						</a>
					<?php endif; ?>
				</div>
			</div>
		</div>
	</div>
	<script>
	(function(){
		var root = document.currentScript && document.currentScript.previousElementSibling;
		if(!root || !root.classList || !root.classList.contains('by-b2b')) { return; }
		var open = root.querySelector('.by-b2b-open');
		var modal = root.querySelector('.by-b2b-modal');
		if(!open || !modal) { return; }
		function show(){
			modal.removeAttribute('hidden');
			document.body.style.overflow = 'hidden';
			var f = modal.querySelector('input,textarea,button');
			if(f && f.focus) { try { f.focus(); } catch(e){} }
		}
		function hide(){
			modal.setAttribute('hidden','');
			document.body.style.overflow = '';
			if(open.focus) { try { open.focus(); } catch(e){} }
		}
		open.addEventListener('click', show);
		modal.addEventListener('click', function(ev){
			if(ev.target && ev.target.hasAttribute &&
			   ev.target.hasAttribute('data-by-b2b-dismiss')) { hide(); }
		});
		document.addEventListener('keydown', function(ev){
			if(ev.key === 'Escape' && !modal.hasAttribute('hidden')) { hide(); }
		});
	})();
	</script>
	<?php
	$busy = false;
}
add_action( 'woocommerce_single_product_summary', 'by_b2b_render_widget', 45 );

/**
 * 诊断 ping：控制台哨兵靠它确认插件在线和版本。
 * 用 barong_cs_key 做钥匙，和别的瘦插件同一套。
 */
function by_b2b_ping() {
	if ( ! isset( $_GET['by-b2b-ping'] ) ) { // phpcs:ignore WordPress.Security.NonceVerification.Recommended
		return;
	}
	$key = get_option( 'barong_cs_key', '' );
	$got = sanitize_text_field( wp_unslash( (string) $_GET['by-b2b-ping'] ) ); // phpcs:ignore WordPress.Security.NonceVerification.Recommended
	if ( '' === $key || ! hash_equals( (string) $key, $got ) ) {
		return;
	}
	$policy = by_b2b_policy();
	header( 'Content-Type: application/json; charset=utf-8' );
	echo wp_json_encode(
		array(
			'ok'            => true,
			'version'       => BY_B2B_VERSION,
			'policy_loaded' => ! empty( $policy ),
			'policy_count'  => isset( $policy['policies'] ) && is_array( $policy['policies'] )
				? count( $policy['policies'] )
				: 0,
		)
	);
	exit;
}
add_action( 'template_redirect', 'by_b2b_ping', 0 );
