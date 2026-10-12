/** GlucoTwin mark: a glucose trace and a forecast point on a small black square. Flat; no gradient or glow. */
export function BrandMark({ size = 28 }: { size?: number }) {
  return (
    <span className="brand__mark" style={{ width: size, height: size }} aria-hidden>
      <svg width={size * 0.68} height={size * 0.68} viewBox="0 0 24 24" fill="none">
        <path d="M3 16.5c2.4 0 3-4.6 5.6-4.6s2.6 3.8 5 3.8 2.4-2.6 4.9-2.6"
          stroke="#fff" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
        <circle cx="18.6" cy="7" r="2.6" fill="#3B82F6" />
      </svg>
    </span>
  );
}

/** Mark + wordmark. The caller decides whether it is a link. */
export function Wordmark({ sub }: { sub?: string }) {
  return (
    <>
      <BrandMark />
      <span className="brand__text">
        <span className="brand__name">GlucoTwin</span>
        {sub && <span className="brand__sub">{sub}</span>}
      </span>
    </>
  );
}
