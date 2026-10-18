import { useEffect, useState } from "react";

/**
 * Mounts an Observable Plot chart into a container and re-renders it when the container is
 * resized (charts fit phones) or when `deps` change. Returns a callback ref for the container.
 */
export function usePlot(
  build: (width: number) => Element,
  deps: readonly unknown[],
): (el: HTMLDivElement | null) => void {
  const [el, setEl] = useState<HTMLDivElement | null>(null);
  const [width, setWidth] = useState(0);

  useEffect(() => {
    if (!el) return;
    const measure = (w: number) =>
      setWidth((prev) => (Math.abs(prev - w) > 4 ? Math.floor(w) : prev));
    measure(el.getBoundingClientRect().width || 600);
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(([entry]) => {
      if (entry && entry.contentRect.width > 0) measure(entry.contentRect.width);
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, [el]);

  useEffect(() => {
    if (!el || width <= 0) return;
    const chart = build(width);
    fixPlotAria(chart);
    el.replaceChildren(chart);
    return () => chart.remove();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- callers pass explicit deps
  }, [el, width, ...deps]);

  return setEl;
}

/**
 * Observable Plot labels each mark's <g> with aria-label, which ARIA prohibits on generic
 * groups. Keep the chart-level label on the <svg> (as role="img") and drop the rest; the
 * figure caption and data table carry the details. Legend swatch SVGs are decorative.
 */
function fixPlotAria(chart: Element) {
  chart.querySelectorAll("g[aria-label]").forEach((g) => g.removeAttribute("aria-label"));
  const svgs = chart.tagName.toLowerCase() === "svg" ? [chart] : [...chart.querySelectorAll("svg")];
  for (const svg of svgs) {
    if (svg.getAttribute("aria-label")) svg.setAttribute("role", "img");
    else svg.setAttribute("aria-hidden", "true");
  }
}
