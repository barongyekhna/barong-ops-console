"use client";

import styles from "./C19Workspace.module.css";
import {
  isCostCardExpired,
  type ParsedCostCard,
} from "./c19CostCard";

export { parseC19CostCard, type ParsedCostCard } from "./c19CostCard";

/**
 * M 系列的「出货明细卡」：制造公司把一份成本快照发过来，这里渲染成表格。
 *
 * 两种口径长得不一样，而且差别是**内容上的**而非显示上的：`priceOnly` 的卡片里
 * 根本没有成本行——发的时候就没放进去，所以这里也无从显示。
 *
 * 过期的卡片整张压暗：报价有效期不是摆设，含铜价类波动料的表 7 天就作废，
 * 拿着一张两周前的表去谈价钱是要吃亏的。
 */
export function C19CostCard({ card }: { card: ParsedCostCard }) {
  const expired = isCostCardExpired(card);

  return (
    <div className={styles.costCard} data-expired={expired ? "true" : "false"}>
      <div className={styles.costCardHead}>
        <span className={styles.costCardKicker}>出货明细</span>
        <span className={styles.costCardNo}>{card.sheetNo}</span>
      </div>

      <div className={styles.costCardTitle}>{card.title}</div>

      {expired ? (
        <p className={styles.costCardExpired}>
          这份报价已过有效期（{card.expires}），请向对方索取最新版。
        </p>
      ) : null}

      {card.shortage ? (
        <p className={styles.costCardShortage}>{card.shortage}</p>
      ) : null}

      {card.materials.length ? (
        <div className={styles.costCardTableWrap}>
          <table className={styles.costCardTable}>
            <thead>
              <tr>
                <th>物料</th>
                <th>用量</th>
                <th>单价</th>
                <th>运费</th>
                <th>小计</th>
              </tr>
            </thead>
            <tbody>
              {card.materials.map((row, index) => (
                <tr key={`${row.code}-${index}`}>
                  <td>
                    <span className={styles.costCardCode}>{row.code}</span>
                    {row.name}
                  </td>
                  <td>{row.qty}</td>
                  <td>{row.unitPrice}</td>
                  <td>{row.unitFreight}</td>
                  <td>{row.lineTotal}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      {card.labor.length ? (
        <div className={styles.costCardTableWrap}>
          <table className={styles.costCardTable}>
            <thead>
              <tr>
                <th>人工</th>
                <th>计价</th>
                <th>工价</th>
                <th>小计</th>
              </tr>
            </thead>
            <tbody>
              {card.labor.map((row, index) => (
                <tr key={`${row.name}-${index}`}>
                  <td>{row.name}</td>
                  <td>{row.mode}</td>
                  <td>{row.rate}</td>
                  <td>{row.lineTotal}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      <dl className={styles.costCardFooter}>
        {card.batch ? (
          <div>
            <dt>批量</dt>
            <dd>{card.batch}</dd>
          </div>
        ) : null}
        {card.totals ? (
          <div>
            <dt>成本</dt>
            <dd>{card.totals}</dd>
          </div>
        ) : null}
        {card.price ? (
          <div className={styles.costCardPrice}>
            <dt>报价</dt>
            <dd>{card.price}</dd>
          </div>
        ) : null}
        {card.expires ? (
          <div>
            <dt>有效期</dt>
            <dd>{card.expires}</dd>
          </div>
        ) : null}
      </dl>
    </div>
  );
}
