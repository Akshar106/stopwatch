/** Props for the panel controlled by <Tabs idPrefix=…>. */
export function tabPanelProps(idPrefix: string, value: string | number) {
  return {
    role: "tabpanel" as const,
    id: `${idPrefix}-panel`,
    "aria-labelledby": `${idPrefix}-tab-${String(value)}`,
    tabIndex: 0,
  };
}
