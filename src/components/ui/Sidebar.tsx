import type { ReactNode } from "react";
import { PanelLeftClose, PanelLeftOpen } from "lucide-react";

export interface SidebarItem {
  id: string;
  label: string;
  icon: ReactNode;
  badge?: string;
}

export interface SidebarProps {
  items: SidebarItem[];
  footerItems?: SidebarItem[];
  activeId: string;
  collapsed: boolean;
  onSelect: (id: string) => void;
  onToggleCollapse: () => void;
}

export function Sidebar({
  items,
  footerItems = [],
  activeId,
  collapsed,
  onSelect,
  onToggleCollapse,
}: SidebarProps) {
  return (
    <aside className={`sidebar ${collapsed ? "collapsed" : ""}`}>
      <nav className="sidebar-nav" aria-label="Điều hướng chính">
        {items.map((item) => (
          <button
            key={item.id}
            type="button"
            className={`sidebar-item ${activeId === item.id ? "active" : ""}`}
            onClick={() => onSelect(item.id)}
            title={collapsed ? item.label : undefined}
          >
            <span style={{ display: "inline-flex", flexShrink: 0 }}>{item.icon}</span>
            {!collapsed && <span>{item.label}</span>}
            {!collapsed && item.badge && <span className="sidebar-badge">{item.badge}</span>}
          </button>
        ))}
      </nav>

      <div className="sidebar-footer">
        {footerItems.map((item) => (
          <button
            key={item.id}
            type="button"
            className={`sidebar-item ${activeId === item.id ? "active" : ""}`}
            onClick={() => onSelect(item.id)}
            title={collapsed ? item.label : undefined}
          >
            <span style={{ display: "inline-flex", flexShrink: 0 }}>{item.icon}</span>
            {!collapsed && <span>{item.label}</span>}
          </button>
        ))}
        <button
          type="button"
          className="sidebar-item"
          onClick={onToggleCollapse}
          title={collapsed ? "Mở rộng thanh bên" : "Thu gọn thanh bên"}
        >
          <span style={{ display: "inline-flex", flexShrink: 0 }}>
            {collapsed ? <PanelLeftOpen size={20} /> : <PanelLeftClose size={20} />}
          </span>
          {!collapsed && <span>Thu gọn</span>}
        </button>
      </div>
    </aside>
  );
}
