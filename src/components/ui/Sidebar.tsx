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
  version?: string;
  hasUpdate?: boolean;
  onSelect: (id: string) => void;
  onToggleCollapse: () => void;
  onVersionClick?: () => void;
}

export function Sidebar({
  items,
  footerItems = [],
  activeId,
  collapsed,
  version,
  hasUpdate = false,
  onSelect,
  onToggleCollapse,
  onVersionClick,
}: SidebarProps) {
  const versionTag = version ? `v${version.replace(/^v/i, "")}` : "";

  return (
    <aside className={`sidebar ${collapsed ? "collapsed" : ""}`}>
      <nav className="sidebar-nav" aria-label="Điều hướng chính">
        {items.map((item) => (
          <button
            key={item.id}
            type="button"
            className={`sidebar-item ${activeId === item.id ? "active" : ""}`}
            onClick={() => onSelect(item.id)}
            title={
              collapsed
                ? item.badge
                  ? `${item.label} (${item.badge})`
                  : item.label
                : undefined
            }
            aria-label={item.label}
          >
            <span className="sidebar-icon-wrap">{item.icon}</span>
            {!collapsed && (
              <span style={{ overflow: "hidden", textOverflow: "ellipsis" }}>{item.label}</span>
            )}
            {!collapsed && item.badge && <span className="sidebar-badge">{item.badge}</span>}
          </button>
        ))}
      </nav>

      <div className="sidebar-footer">
        {footerItems.map((item) => {
          const isSettings = item.id === "settings";
          const collapsedTip =
            isSettings && versionTag
              ? `${item.label} · ${versionTag}${hasUpdate ? " (Có bản cập nhật mới)" : ""}`
              : item.label;
          return (
            <button
              key={item.id}
              type="button"
              className={`sidebar-item ${activeId === item.id ? "active" : ""}`}
              onClick={() => onSelect(item.id)}
              title={collapsed ? collapsedTip : undefined}
              aria-label={item.label}
            >
              <span className="sidebar-icon-wrap">
                {item.icon}
                {collapsed && isSettings && hasUpdate && <span className="sidebar-update-dot" />}
              </span>
              {!collapsed && (
                <span style={{ overflow: "hidden", textOverflow: "ellipsis" }}>{item.label}</span>
              )}
              {!collapsed && isSettings && hasUpdate && (
                <span className="sidebar-badge">Mới</span>
              )}
            </button>
          );
        })}
        <button
          type="button"
          className="sidebar-item"
          onClick={onToggleCollapse}
          title={
            collapsed
              ? versionTag
                ? `Mở rộng thanh bên (${versionTag})`
                : "Mở rộng thanh bên"
              : "Thu gọn thanh bên"
          }
          aria-label={collapsed ? "Mở rộng thanh bên" : "Thu gọn thanh bên"}
        >
          <span className="sidebar-icon-wrap">
            {collapsed ? <PanelLeftOpen size={20} /> : <PanelLeftClose size={20} />}
          </span>
          {!collapsed && <span>Thu gọn</span>}
        </button>

        {!collapsed && versionTag && (
          <button
            type="button"
            className="sidebar-version"
            onClick={onVersionClick}
            title={
              hasUpdate
                ? `Phiên bản hiện tại ${versionTag} — Có bản cập nhật mới`
                : `Phiên bản hiện tại ${versionTag}`
            }
          >
            <span>{versionTag}</span>
            {hasUpdate && <span className="sidebar-update-dot" />}
          </button>
        )}
      </div>
    </aside>
  );
}
