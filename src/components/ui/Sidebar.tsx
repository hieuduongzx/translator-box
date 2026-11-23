import type { ReactNode } from "react";
import { PanelLeftClose, PanelLeftOpen, Settings } from "lucide-react";

export interface SidebarItem {
  id: string;
  label: string;
  icon: ReactNode;
  badge?: string | number;
  badgeVariant?: "neutral" | "warning" | "accent";
}

export interface SidebarProps {
  items: SidebarItem[];
  activeId: string;
  onSelect: (id: string) => void;
  collapsed: boolean;
  onToggleCollapse: () => void;
  settingsId?: string;
  settingsLabel?: string;
  settingsBadge?: string;
  hasUpdate?: boolean;
  version?: string;
  onVersionClick?: () => void;
  children?: ReactNode;
  footerExtra?: ReactNode;
}

export function Sidebar({
  items,
  activeId,
  onSelect,
  collapsed,
  onToggleCollapse,
  settingsId = "settings",
  settingsLabel = "Cài đặt",
  settingsBadge,
  hasUpdate = false,
  version,
  onVersionClick,
  children,
  footerExtra,
}: SidebarProps) {
  const cleanVersion = version ? (version.startsWith("v") ? version : `v${version}`) : "";
  const settingsActive = activeId === settingsId;
  const collapsedSettingsTitle = cleanVersion
    ? hasUpdate
      ? `${settingsLabel} · ${cleanVersion} (Có bản cập nhật mới)`
      : `${settingsLabel} · ${cleanVersion}`
    : hasUpdate
      ? `${settingsLabel} (Có bản cập nhật mới)`
      : settingsLabel;

  const handleVersionClick = () => {
    if (onVersionClick) {
      onVersionClick();
    } else {
      onSelect(settingsId);
    }
  };

  return (
    <aside className={`ui-sidebar${collapsed ? " collapsed" : ""}`}>
      <nav
        className={`ui-sidebar-nav${!collapsed && children ? " has-body" : ""}`}
        aria-label="Điều hướng chính"
      >
        {items.map((item) => {
          const isActive = activeId === item.id;
          return (
            <button
              key={item.id}
              type="button"
              className={`ui-sidebar-item${isActive ? " active" : ""}`}
              aria-current={isActive ? "page" : undefined}
              aria-label={item.label}
              title={collapsed ? item.label : undefined}
              onClick={() => onSelect(item.id)}
            >
              <span className="ui-sidebar-icon">{item.icon}</span>
              {!collapsed && <span className="ui-sidebar-label">{item.label}</span>}
              {!collapsed && item.badge !== undefined && item.badge !== "" && (
                <span
                  className={`ui-sidebar-badge${
                    item.badgeVariant && item.badgeVariant !== "neutral"
                      ? ` ${item.badgeVariant}`
                      : ""
                  }`}
                >
                  {item.badge}
                </span>
              )}
            </button>
          );
        })}
      </nav>

      {!collapsed && children && <div className="ui-sidebar-body">{children}</div>}

      <div className="ui-sidebar-footer">
        {!collapsed && footerExtra}

        <button
          type="button"
          className={`ui-sidebar-item${settingsActive ? " active" : ""}`}
          aria-current={settingsActive ? "page" : undefined}
          aria-label={settingsLabel}
          title={collapsed ? collapsedSettingsTitle : undefined}
          onClick={() => onSelect(settingsId)}
        >
          <span className="ui-sidebar-icon">
            <Settings size={20} />
          </span>
          {!collapsed && <span className="ui-sidebar-label">{settingsLabel}</span>}
          {!collapsed && settingsBadge && (
            <span className="ui-sidebar-badge accent">{settingsBadge}</span>
          )}
          {hasUpdate && !settingsBadge && (
            <span className="ui-sidebar-dot" aria-label="Có bản cập nhật mới" />
          )}
        </button>

        <button
          type="button"
          className="ui-sidebar-item"
          aria-label={collapsed ? "Mở rộng thanh bên" : "Thu gọn thanh bên"}
          aria-expanded={!collapsed}
          title={collapsed ? "Mở rộng thanh bên" : "Thu gọn thanh bên"}
          onClick={onToggleCollapse}
        >
          <span className="ui-sidebar-icon">
            {collapsed ? <PanelLeftOpen size={20} /> : <PanelLeftClose size={20} />}
          </span>
          {!collapsed && <span className="ui-sidebar-label">Thu gọn</span>}
        </button>

        {!collapsed && cleanVersion && (
          <button
            type="button"
            className="ui-sidebar-version"
            title={
              hasUpdate
                ? `Phiên bản ${cleanVersion} — Có bản cập nhật mới, nhấn để mở Cài đặt`
                : `Phiên bản ${cleanVersion} — Nhấn để mở Cài đặt & kiểm tra cập nhật`
            }
            onClick={handleVersionClick}
          >
            <span>{cleanVersion}</span>
            {hasUpdate && <span className="ui-sidebar-dot" aria-hidden="true" />}
          </button>
        )}
      </div>
    </aside>
  );
}
