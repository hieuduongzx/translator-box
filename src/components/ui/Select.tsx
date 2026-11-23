import {
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent as ReactKeyboardEvent,
  type ReactNode,
  type RefObject,
} from "react";
import { createPortal } from "react-dom";
import { Check, ChevronDown, Search } from "lucide-react";

/* ───────────────────────────── Popover neo theo phần tử ─────────────────────────────
 * Render qua portal vào <body> (không bị overflow của container cắt), position: fixed.
 * - Cách mép neo 4px, cách mép cửa sổ tối thiểu 8px.
 * - Chiều cao tối đa = khoảng trống còn lại; phía dưới không đủ thì tự lật lên trên.
 * - Đóng khi bấm ra ngoài, cuộn trang (ngoài popover), đổi cỡ cửa sổ, mất focus cửa sổ.
 */

const POPOVER_GAP = 4;
const VIEWPORT_MARGIN = 8;

export interface PopoverProps {
  anchorRef: RefObject<HTMLElement | null>;
  open: boolean;
  onClose: () => void;
  children: ReactNode;
  /** Căn theo mép trái (start) hoặc mép phải (end) của phần tử neo. */
  align?: "start" | "end";
  /** Rộng tối thiểu bằng phần tử neo (mặc định true). */
  matchWidth?: boolean;
  minWidth?: number;
  /** Trần chiều cao (px), vẫn bị giới hạn bởi khoảng trống thực tế. */
  maxHeight?: number;
  /** Trần chiều rộng (px); không bao giờ nhỏ hơn phần tử neo khi matchWidth. */
  maxWidth?: number;
  className?: string;
  style?: CSSProperties;
  role?: string;
  id?: string;
  /** Gọi sau mỗi lần định vị lại (để cuộn tới mục đang chọn...). */
  onPositioned?: () => void;
  /** Thay đổi giá trị này để buộc tính lại vị trí (ví dụ khi lọc danh sách). */
  layoutKey?: unknown;
}

interface PopoverPos {
  left: number;
  top?: number;
  bottom?: number;
  maxHeight: number;
  minWidth: number;
  maxWidth: number;
  placement: "bottom" | "top";
}

export function Popover({
  anchorRef,
  open,
  onClose,
  children,
  align = "start",
  matchWidth = true,
  minWidth = 0,
  maxHeight = 400,
  maxWidth,
  className = "",
  style,
  role,
  id,
  onPositioned,
  layoutKey,
}: PopoverProps) {
  const popRef = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState<PopoverPos | null>(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;
  const onPositionedRef = useRef(onPositioned);
  onPositionedRef.current = onPositioned;

  const place = useCallback(() => {
    const anchor = anchorRef.current;
    const pop = popRef.current;
    if (!anchor || !pop) return;
    const r = anchor.getBoundingClientRect();
    const vw = document.documentElement.clientWidth || window.innerWidth;
    const vh = document.documentElement.clientHeight || window.innerHeight;
    const minW = Math.min(Math.max(matchWidth ? r.width : 0, minWidth), vw - VIEWPORT_MARGIN * 2);

    // Đo chiều cao tự nhiên (không giới hạn) để quyết định lật lên/xuống.
    const maxW = Math.min(vw - VIEWPORT_MARGIN * 2, Math.max(minW, maxWidth ?? Infinity));
    pop.style.maxHeight = "none";
    pop.style.minWidth = `${minW}px`;
    pop.style.maxWidth = `${maxW}px`;
    const natural = pop.scrollHeight;
    const width = Math.min(pop.offsetWidth, vw - VIEWPORT_MARGIN * 2);

    const below = vh - r.bottom - POPOVER_GAP - VIEWPORT_MARGIN;
    const above = r.top - POPOVER_GAP - VIEWPORT_MARGIN;
    const want = Math.min(natural, maxHeight);
    const placement: "bottom" | "top" = want <= below || below >= above ? "bottom" : "top";
    const room = Math.max(placement === "bottom" ? below : above, 48);

    let left = align === "end" ? r.right - width : r.left;
    left = Math.min(left, vw - VIEWPORT_MARGIN - width);
    left = Math.max(left, VIEWPORT_MARGIN);

    pop.style.maxHeight = "";
    setPos({
      left,
      top: placement === "bottom" ? r.bottom + POPOVER_GAP : undefined,
      bottom: placement === "top" ? vh - r.top + POPOVER_GAP : undefined,
      maxHeight: Math.min(room, maxHeight),
      minWidth: minW,
      maxWidth: maxW,
      placement,
    });
  }, [anchorRef, align, matchWidth, minWidth, maxHeight, maxWidth]);

  useLayoutEffect(() => {
    if (!open) {
      setPos(null);
      return;
    }
    place();
  }, [open, place, layoutKey]);

  useLayoutEffect(() => {
    if (open && pos) onPositionedRef.current?.();
    // chỉ chạy khi vị trí vừa được tính
  }, [open, pos]);

  useEffect(() => {
    if (!open) return;
    const isInside = (t: EventTarget | null) => {
      const n = t as Node | null;
      if (!n) return false;
      return Boolean(popRef.current?.contains(n) || anchorRef.current?.contains(n));
    };
    const onDown = (e: PointerEvent) => {
      if (!isInside(e.target)) onCloseRef.current();
    };
    // Chỉ đóng khi vùng vừa cuộn có chứa ô neo (ô bị dời chỗ); bỏ qua cuộn bên trong popover
    // hoặc ở khung khác (ví dụ khung dịch tự cuộn khi có chữ mới).
    const onScroll = (e: Event) => {
      const t = e.target;
      const anchor = anchorRef.current;
      if (t instanceof Node && popRef.current?.contains(t)) return;
      if (t === document || t === window || (t instanceof Node && anchor && t.contains(anchor))) {
        onCloseRef.current();
      }
    };
    const onResize = () => onCloseRef.current();
    const onBlur = () => onCloseRef.current();
    window.addEventListener("pointerdown", onDown, true);
    window.addEventListener("scroll", onScroll, true);
    window.addEventListener("resize", onResize);
    window.addEventListener("blur", onBlur);
    return () => {
      window.removeEventListener("pointerdown", onDown, true);
      window.removeEventListener("scroll", onScroll, true);
      window.removeEventListener("resize", onResize);
      window.removeEventListener("blur", onBlur);
    };
  }, [open, anchorRef]);

  if (!open) return null;

  const posStyle: CSSProperties = pos
    ? {
        left: pos.left,
        top: pos.top,
        bottom: pos.bottom,
        maxHeight: pos.maxHeight,
        minWidth: pos.minWidth,
        maxWidth: pos.maxWidth,
      }
    : { left: -9999, top: 0, visibility: "hidden" };

  return createPortal(
    <div
      ref={popRef}
      id={id}
      role={role}
      className={`ui-popover ${pos?.placement === "top" ? "is-top" : ""} ${className}`.trim()}
      style={{ ...style, ...posStyle }}
    >
      {children}
    </div>,
    document.body
  );
}

/* ───────────────────────────── Select ───────────────────────────── */

export interface SelectOption<V extends string = string> {
  value: V;
  label: string;
  /** Dòng mô tả phụ (chữ nhỏ, màu mờ). */
  description?: string;
  icon?: ReactNode;
  disabled?: boolean;
  /** Tên nhóm; các mục cùng nhóm được gom dưới một tiêu đề. */
  group?: string;
}

export interface SelectProps<V extends string = string> {
  value: V | null | undefined;
  onChange: (value: V) => void;
  options: readonly SelectOption<V>[];
  placeholder?: string;
  disabled?: boolean;
  /** Ô tìm kiếm: mặc định tự bật khi > 10 mục. */
  searchable?: boolean;
  searchPlaceholder?: string;
  size?: "sm" | "md";
  /** Kéo giãn ô chọn hết chiều ngang khung chứa. */
  block?: boolean;
  className?: string;
  style?: CSSProperties;
  id?: string;
  title?: string;
  "aria-label"?: string;
  /** Nội dung tuỳ biến trên ô chọn (mặc định: icon + nhãn của mục đang chọn). */
  renderValue?: (selected: SelectOption<V> | undefined) => ReactNode;
  /** Căn danh sách theo mép phải ô chọn (dùng khi ô nằm sát mép phải). */
  align?: "start" | "end";
}

const SEARCH_THRESHOLD = 10;
/** Số mục tối đa dùng để đo bề rộng ô chọn (ô tự rộng theo mục dài nhất như <select> gốc). */
const SIZER_LIMIT = 200;
const POPOVER_MAX_WIDTH = 360;

/** Bỏ dấu tiếng Việt + chữ thường để tìm kiếm/nhảy chữ. */
export function normalizeSearchText(s: string): string {
  return s
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/đ/g, "d")
    .replace(/Đ/g, "D")
    .toLowerCase()
    .trim();
}

export function Select<V extends string = string>({
  value,
  onChange,
  options,
  placeholder = "Chọn…",
  disabled = false,
  searchable,
  searchPlaceholder = "Tìm…",
  size = "md",
  block = false,
  className = "",
  style,
  id,
  title,
  "aria-label": ariaLabel,
  renderValue,
  align = "start",
}: SelectProps<V>) {
  const autoId = useId();
  const listId = `${id ?? autoId}-list`;
  const triggerRef = useRef<HTMLButtonElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(-1);
  const typeahead = useRef({ buf: "", t: 0 });
  const scrollMode = useRef<"center" | "nearest">("center");

  const showSearch = searchable ?? options.length > SEARCH_THRESHOLD;
  const selected = options.find((o) => o.value === value);

  const filtered = useMemo(() => {
    const q = normalizeSearchText(query);
    if (!q) return options;
    return options.filter((o) =>
      normalizeSearchText(`${o.label} ${o.description ?? ""} ${o.group ?? ""}`).includes(q)
    );
  }, [options, query]);

  // Gom nhóm theo thứ tự xuất hiện đầu tiên, giữ chỉ số phẳng để điều hướng.
  const flat = useMemo(() => {
    const order: string[] = [];
    const byGroup = new Map<string, SelectOption<V>[]>();
    for (const o of filtered) {
      const g = o.group ?? "";
      if (!byGroup.has(g)) {
        byGroup.set(g, []);
        order.push(g);
      }
      byGroup.get(g)!.push(o);
    }
    return order.flatMap((g) => byGroup.get(g)!);
  }, [filtered]);

  const firstEnabled = useCallback(
    (from: number, dir: 1 | -1) => {
      for (let i = from; i >= 0 && i < flat.length; i += dir) {
        if (!flat[i].disabled) return i;
      }
      return -1;
    },
    [flat]
  );

  const openList = useCallback(
    (seed = "") => {
      if (disabled) return;
      setQuery(seed);
      scrollMode.current = "center";
      setOpen(true);
    },
    [disabled]
  );

  const close = useCallback((refocus = false) => {
    setOpen(false);
    setQuery("");
    if (refocus) triggerRef.current?.focus();
  }, []);

  const commit = useCallback(
    (opt: SelectOption<V> | undefined) => {
      if (!opt || opt.disabled) return;
      close(true);
      if (opt.value !== value) onChange(opt.value);
    },
    [close, onChange, value]
  );

  // Khi mở / đổi bộ lọc: chọn mục đang chọn (hoặc mục đầu tiên hợp lệ).
  useEffect(() => {
    if (!open) return;
    const idx = query ? -1 : flat.findIndex((o) => o.value === value);
    setActive(idx >= 0 && !flat[idx].disabled ? idx : firstEnabled(0, 1));
  }, [open, query, flat, value, firstEnabled]);

  // Focus vào ô tìm kiếm hoặc danh sách khi mở.
  useEffect(() => {
    if (!open) return;
    const t = window.setTimeout(() => {
      if (showSearch) searchRef.current?.focus({ preventScroll: true });
      else listRef.current?.focus({ preventScroll: true });
    }, 0);
    return () => window.clearTimeout(t);
  }, [open, showSearch]);

  const scrollActiveIntoView = useCallback(() => {
    const list = listRef.current;
    if (!list || active < 0) return;
    const el = list.querySelector<HTMLElement>(`[data-index="${active}"]`);
    if (!el) return;
    if (scrollMode.current === "center") {
      list.scrollTop = el.offsetTop - list.clientHeight / 2 + el.offsetHeight / 2;
    } else {
      const top = el.offsetTop;
      const bottom = top + el.offsetHeight;
      if (top < list.scrollTop) list.scrollTop = top;
      else if (bottom > list.scrollTop + list.clientHeight)
        list.scrollTop = bottom - list.clientHeight;
    }
  }, [active]);

  useLayoutEffect(() => {
    if (open) scrollActiveIntoView();
  }, [open, active, scrollActiveIntoView]);

  const move = (to: number) => {
    scrollMode.current = "nearest";
    setActive(to);
  };

  const handleTypeahead = (ch: string) => {
    const now = Date.now();
    const ta = typeahead.current;
    ta.buf = now - ta.t > 600 ? ch : ta.buf + ch;
    ta.t = now;
    const q = normalizeSearchText(ta.buf);
    const start = ta.buf.length === 1 ? active + 1 : Math.max(active, 0);
    for (let k = 0; k < flat.length; k++) {
      const i = (start + k) % flat.length;
      const o = flat[i];
      if (!o.disabled && normalizeSearchText(o.label).startsWith(q)) {
        move(i);
        return;
      }
    }
  };

  const onListKeyDown = (e: ReactKeyboardEvent) => {
    const page = 8;
    switch (e.key) {
      case "ArrowDown": {
        e.preventDefault();
        const n = firstEnabled(active + 1, 1);
        if (n >= 0) move(n);
        return;
      }
      case "ArrowUp": {
        e.preventDefault();
        const n = firstEnabled(active - 1, -1);
        if (n >= 0) move(n);
        return;
      }
      case "Home":
        e.preventDefault();
        move(firstEnabled(0, 1));
        return;
      case "End":
        e.preventDefault();
        move(firstEnabled(flat.length - 1, -1));
        return;
      case "PageDown": {
        e.preventDefault();
        const n = firstEnabled(Math.min(active + page, flat.length - 1), -1);
        if (n >= 0) move(n);
        return;
      }
      case "PageUp": {
        e.preventDefault();
        const n = firstEnabled(Math.max(active - page, 0), 1);
        if (n >= 0) move(n);
        return;
      }
      case "Enter":
        e.preventDefault();
        commit(flat[active]);
        return;
      case "Escape":
        e.preventDefault();
        e.stopPropagation();
        close(true);
        return;
      case "Tab":
        close(false);
        return;
      default:
        if (!showSearch && e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {
          e.preventDefault();
          handleTypeahead(e.key);
        }
    }
  };

  const onTriggerKeyDown = (e: ReactKeyboardEvent<HTMLButtonElement>) => {
    if (open || disabled) return;
    if (["ArrowDown", "ArrowUp", "Enter", " ", "F4"].includes(e.key)) {
      e.preventDefault();
      openList();
      return;
    }
    if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {
      e.preventDefault();
      if (showSearch) {
        openList(e.key);
      } else {
        // Ô đóng: gõ chữ để nhảy giá trị (như <select> gốc).
        const q = normalizeSearchText(e.key);
        const cur = options.findIndex((o) => o.value === value);
        for (let k = 1; k <= options.length; k++) {
          const o = options[(cur + k) % options.length];
          if (!o.disabled && normalizeSearchText(o.label).startsWith(q)) {
            if (o.value !== value) onChange(o.value);
            break;
          }
        }
      }
    }
  };

  const activeOpt = active >= 0 ? flat[active] : undefined;
  const activeId = activeOpt ? `${listId}-${active}` : undefined;

  let lastGroup: string | undefined;
  const items: ReactNode[] = [];
  flat.forEach((o, i) => {
    const g = o.group ?? "";
    if (g && g !== lastGroup) {
      items.push(
        <div key={`g-${g}-${i}`} className="ui-select-group" role="presentation">
          {g}
        </div>
      );
    }
    lastGroup = g;
    const isSel = o.value === value;
    items.push(
      <div
        key={`${o.value}-${i}`}
        id={`${listId}-${i}`}
        data-index={i}
        role="option"
        aria-selected={isSel}
        aria-disabled={o.disabled || undefined}
        className={`ui-select-option${i === active ? " is-active" : ""}${isSel ? " is-selected" : ""}${
          o.disabled ? " is-disabled" : ""
        }`}
        onPointerMove={() => {
          if (!o.disabled && i !== active) {
            scrollMode.current = "nearest";
            setActive(i);
          }
        }}
        onPointerDown={(e) => e.preventDefault()}
        onClick={() => commit(o)}
        title={o.description ? `${o.label} — ${o.description}` : o.label}
      >
        {o.icon && <span className="ui-select-option-icon">{o.icon}</span>}
        <span className="ui-select-option-text">
          <span className="ui-select-option-label">{o.label}</span>
          {o.description && <span className="ui-select-option-desc">{o.description}</span>}
        </span>
        <span className="ui-select-option-check">{isSel && <Check size={14} />}</span>
      </div>
    );
  });

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        id={id}
        role="combobox"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={open ? listId : undefined}
        aria-label={ariaLabel}
        title={title ?? selected?.label}
        disabled={disabled}
        className={`ui-select-trigger ui-select-${size}${block ? " is-block" : ""}${
          open ? " is-open" : ""
        } ${className}`.trim()}
        style={style}
        onClick={() => (open ? close(false) : openList())}
        onKeyDown={onTriggerKeyDown}
      >
        {renderValue ? (
          <span className="ui-select-value">{renderValue(selected)}</span>
        ) : (
          <>
            {selected?.icon && <span className="ui-select-option-icon">{selected.icon}</span>}
            <span className={`ui-select-value${selected ? "" : " is-placeholder"}`}>
              <span className="ui-select-value-text">
                {selected?.label ?? (value ? String(value) : placeholder)}
              </span>
              {options.slice(0, SIZER_LIMIT).map((o, i) => (
                <span key={`${o.value}-${i}`} className="ui-select-sizer" aria-hidden>
                  {o.label}
                </span>
              ))}
            </span>
          </>
        )}
        <ChevronDown size={size === "sm" ? 14 : 16} className="ui-select-chevron" aria-hidden />
      </button>
      <Popover
        anchorRef={triggerRef}
        open={open}
        onClose={() => close(false)}
        align={align}
        maxWidth={POPOVER_MAX_WIDTH}
        className={`ui-select-popover ui-select-${size}`}
        layoutKey={`${query}|${flat.length}`}
        onPositioned={scrollActiveIntoView}
      >
        {showSearch && (
          <div className="ui-select-search">
            <Search size={14} aria-hidden />
            <input
              ref={searchRef}
              type="text"
              value={query}
              placeholder={searchPlaceholder}
              aria-label={searchPlaceholder}
              aria-controls={listId}
              aria-activedescendant={activeId}
              spellCheck={false}
              autoComplete="off"
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={onListKeyDown}
            />
          </div>
        )}
        <div
          ref={listRef}
          id={listId}
          role="listbox"
          tabIndex={-1}
          aria-label={ariaLabel}
          aria-activedescendant={showSearch ? undefined : activeId}
          className="ui-select-list"
          onKeyDown={showSearch ? undefined : onListKeyDown}
        >
          {items.length ? items : <div className="ui-select-empty">Không tìm thấy kết quả</div>}
        </div>
      </Popover>
    </>
  );
}
