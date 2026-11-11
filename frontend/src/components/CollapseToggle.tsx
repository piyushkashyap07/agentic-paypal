// Small arrow button that folds a section open (▴) or closed (▾).
export default function CollapseToggle({
  open,
  onToggle,
  label,
}: {
  open: boolean;
  onToggle: () => void;
  label: string;
}) {
  return (
    <button
      type="button"
      className="collapse-toggle"
      aria-expanded={open}
      aria-label={`${open ? "Hide" : "Show"} ${label}`}
      title={`${open ? "Hide" : "Show"} ${label}`}
      onClick={onToggle}
    >
      {open ? "▴" : "▾"}
    </button>
  );
}
