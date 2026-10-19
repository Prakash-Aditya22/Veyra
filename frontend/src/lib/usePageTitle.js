import { useEffect } from 'react';

export const PRODUCT = 'Veyra';
export const PRODUCT_SUBTITLE = 'Great Britain Road Safety Intelligence';

/** Sets the document title per screen ("Explorer · Veyra"), so browsers and screen readers name the page. */
export function usePageTitle(title) {
  useEffect(() => {
    document.title = title ? `${title} · ${PRODUCT}` : `${PRODUCT} · ${PRODUCT_SUBTITLE}`;
  }, [title]);
}
