export interface ToggleProps {
  checked: boolean;
  onChange: (checked: boolean) => void;
  ariaLabel?: string;
}

export function Toggle({ checked, onChange, ariaLabel }: ToggleProps) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={ariaLabel}
      className="ui-toggle"
      data-checked={checked ? "true" : "false"}
      onClick={() => onChange(!checked)}
    >
      <span className="ui-toggle-thumb" />
    </button>
  );
}
