import { useEffect, useState } from "react";
import { api, type SaleItem, type Store as StoreData } from "../api";
import { CHECK_AGAINST, DEMO_DATA_TAG, inr, NOT_DIAGNOSIS, STORE_HELP } from "../copy";
import { ProductArt } from "../components/ProductArt";
import { CartCheckPanel } from "../components/CartCheck";
import { PasteCheck } from "../components/BasketExtras";
import { Btn, IncompleteTag, Loading, NavBar, Notice, PageHead, Section } from "../components/ui";
import { go } from "../router";

// The sale page: the moment docs/STRATEGY.md section 4 calls Moment 1. This is the only screen in
// the app that is new, and it is deliberately the one place that looks like a shop rather than
// like derm//os: the whole point is that "Check against my skin" works from where you actually
// are when you are about to spend money.
export default function Store({ checkId }: { checkId?: string | null }) {
  const [data, setData] = useState<StoreData | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api.store().then(setData, (e) => setErr((e as Error).message));
  }, []);

  if (err)
    return (
      <div className="page">
        <NavBar back="/" />
        <Notice tone="stop">{err}</Notice>
      </div>
    );
  if (!data)
    return (
      <div className="page">
        <NavBar back="/" />
        <Loading label="Opening the sale" />
      </div>
    );

  // The check opens in place, so you never lose the shop you were standing in.
  if (checkId) {
    const item = data.items.find((i) => i.product_id === checkId);
    return (
      <div className="page">
        <NavBar back="/store" />
        <CartCheckPanel
          productId={checkId}
          saleItem={item}
          onBack={() => go("/store")}
        />
      </div>
    );
  }

  return (
    <div className="page page--wide">
      <NavBar back="/" />
      <p className="tag tag--prepared">{DEMO_DATA_TAG} · fictional shop and products</p>
      <PageHead eyebrow={data.name} title={data.line} lede={STORE_HELP} />

      <Section label={`${data.items.length} items on sale`}>
        <ul className="sale">
          {data.items.map((i) => (
            <SaleRow key={i.product_id} item={i} />
          ))}
        </ul>
      </Section>

      <Section label="Check any product">
        <p className="formhelp">Not in this sale? Paste any product's ingredient list and it is checked the same way.</p>
        <PasteCheck />
      </Section>

      <p className="foot small">
        {data.disclaimer} {NOT_DIAGNOSIS}
      </p>
    </div>
  );
}

function SaleRow({ item }: { item: SaleItem }) {
  const p = item.product;
  const off = Math.round(100 - (item.sale_price_inr / p.price_inr) * 100);
  return (
    <li className="sale__item">
      <span className="sale__art">
        <ProductArt product={p} size={64} />
      </span>
      <span className="sale__body">
        <span className="sale__brand">{p.brand}</span>
        <span className="sale__name">{p.name}</span>
        {/* The shop's own words. derm//os checks the label instead of trusting this. */}
        <span className="sale__blurb">{item.blurb}</span>
        <span className="sale__prices">
          <strong className="sale__now">{inr(item.sale_price_inr)}</strong>
          <s className="sale__was">{inr(p.price_inr)}</s>
          {off > 0 && <em className="sale__off">{off}% off</em>}
        </span>
        {!p.inci_complete && <IncompleteTag />}
        <Btn to={`/store/${p.id}`} kind="primary">
          {CHECK_AGAINST}
        </Btn>
      </span>
    </li>
  );
}
