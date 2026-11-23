import { useState } from "react";
import { open as openExternal } from "@tauri-apps/plugin-shell";
import { BookOpen, Bot, ExternalLink, Plus, Save, Trash2 } from "lucide-react";
import { Button, Card, ConfirmDialog, Dialog } from "../components/ui";
import type { ToastKind } from "../hooks";
import { BUILTIN_AI_PROVIDERS } from "../lib/constants";
import type { AppConfig, CustomAiProvider, GlossaryEntry } from "../types";

interface Props {
  config: AppConfig;
  onUpdateConfig: (patch: Partial<AppConfig>) => Promise<void>;
  onToast: (message: string, kind?: ToastKind) => void;
}

function formatGlossary(entries: GlossaryEntry[]): string {
  return entries.map((e) => `${e.source} = ${e.target}`).join("\n");
}

function parseGlossary(raw: string): GlossaryEntry[] {
  const out: GlossaryEntry[] = [];
  for (const line of raw.split(/\r?\n/)) {
    const clean = line.trim();
    if (!clean || clean.startsWith("#") || !clean.includes("=")) continue;
    const idx = clean.indexOf("=");
    const source = clean.slice(0, idx).trim();
    const target = clean.slice(idx + 1).trim();
    if (source && target) out.push({ source, target });
  }
  return out;
}

export function AiProvidersPage({ config, onUpdateConfig, onToast: toast }: Props) {
  const [glossaryText, setGlossaryText] = useState(() =>
    formatGlossary(config.translation_glossary)
  );
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<CustomAiProvider | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<CustomAiProvider | null>(null);

  const [cpName, setCpName] = useState("");
  const [cpEndpoint, setCpEndpoint] = useState("");
  const [cpKey, setCpKey] = useState("");
  const [cpModels, setCpModels] = useState("");

  const openAddDialog = () => {
    setEditing(null);
    setCpName("");
    setCpEndpoint("");
    setCpKey("");
    setCpModels("");
    setDialogOpen(true);
  };

  const openEditDialog = (p: CustomAiProvider) => {
    setEditing(p);
    setCpName(p.name);
    setCpEndpoint(p.endpoint);
    setCpKey(p.api_key);
    setCpModels(p.models.join("\n"));
    setDialogOpen(true);
  };

  const saveCustomProvider = async () => {
    const models = cpModels
      .split(/[\n,]+/)
      .map((s) => s.trim())
      .filter(Boolean);
    if (!cpName.trim() || !cpEndpoint.trim().startsWith("http") || models.length === 0) {
      toast("Vui lòng nhập đầy đủ Tên, Endpoint http(s) và ít nhất 1 model.", "error");
      return;
    }
    const provider: CustomAiProvider = {
      id: editing ? editing.id : `p_${Date.now()}`,
      name: cpName.trim(),
      endpoint: cpEndpoint.trim().replace(/\/+$/, ""),
      api_key: cpKey.trim(),
      models,
    };
    const next = editing
      ? config.custom_providers.map((p) => (p.id === editing.id ? provider : p))
      : [...config.custom_providers, provider];
    await onUpdateConfig({ custom_providers: next });
    setDialogOpen(false);
    toast(editing ? "Đã cập nhật provider tùy chỉnh" : "Đã thêm provider tùy chỉnh", "success");
  };

  const setBuiltinKey = (providerId: string, key: string) => {
    if (providerId === "llm") {
      onUpdateConfig({ llm_api_key: key });
    } else {
      onUpdateConfig({ ai_keys: { ...config.ai_keys, [providerId]: key } });
    }
  };

  return (
    <div className="stack-16">
      <div className="page-header">
        <div>
          <div className="page-title-row">
            <span className="page-title-icon">
              <Bot size={24} />
            </span>
            <h1 className="page-title">Dịch vụ AI &amp; Thuật ngữ</h1>
          </div>
          <p className="page-subtitle">
            Cấu hình API key cho các mô hình AI tích hợp, dịch vụ OpenAI-compatible tùy chỉnh và từ điển thuật ngữ.
          </p>
        </div>
      </div>

      <Card
        title="Nhà cung cấp AI tích hợp"
        description="Nhập API key để mở khoá các mô hình tương ứng trong danh sách dịch vụ dịch."
      >
        {BUILTIN_AI_PROVIDERS.map((p) => {
          const currentKey = p.id === "llm" ? config.llm_api_key : config.ai_keys[p.id] || "";
          return (
            <div key={p.id} className="field-row">
              <div className="field-meta">
                <div className="row-8">
                  <span className="field-label">{p.name}</span>
                  {currentKey.trim() && <span className="badge success">Đã cấu hình</span>}
                </div>
                <span className="field-hint">
                  Mô hình: {p.models.map((m) => m.label).join(" · ")}
                </span>
              </div>
              <div className="field-control">
                <input
                  type="password"
                  className="ui-input"
                  style={{ width: 240 }}
                  placeholder={`API key ${p.name}…`}
                  value={currentKey}
                  onChange={(e) => setBuiltinKey(p.id, e.target.value)}
                />
                <Button
                  variant="ghost"
                  iconOnly
                  title="Lấy API key"
                  aria-label={`Lấy API key ${p.name}`}
                  onClick={() => openExternal(p.register)}
                >
                  <ExternalLink size={16} />
                </Button>
              </div>
            </div>
          );
        })}
      </Card>

      <Card
        title="Nhà cung cấp tùy chỉnh (OpenAI-compatible)"
        description="Hỗ trợ OpenRouter, Ollama, LM Studio hoặc proxy nội bộ chuẩn /v1/chat/completions."
        headerRight={
          <Button variant="primary" onClick={openAddDialog}>
            <Plus size={16} />
            Thêm nhà cung cấp
          </Button>
        }
      >
        {config.custom_providers.length === 0 ? (
          <div className="empty-state">
            <Bot size={20} />
            <span>Chưa có nhà cung cấp tùy chỉnh nào.</span>
          </div>
        ) : (
          <div className="stack-8">
            {config.custom_providers.map((p) => (
              <div key={p.id} className="history-item">
                <div className="row-8" style={{ justifyContent: "space-between", alignItems: "flex-start" }}>
                  <div style={{ minWidth: 0, flex: 1 }}>
                    <strong>{p.name}</strong>
                    <div className="field-hint">{p.endpoint}</div>
                  </div>
                  <div className="field-control">
                    <Button variant="secondary" onClick={() => openEditDialog(p)}>
                      Sửa
                    </Button>
                    <Button
                      variant="ghost"
                      iconOnly
                      title={`Xoá ${p.name}`}
                      aria-label={`Xoá ${p.name}`}
                      onClick={() => setDeleteTarget(p)}
                    >
                      <Trash2 size={16} />
                    </Button>
                  </div>
                </div>
                <div className="row-8">
                  {p.models.map((m) => (
                    <span key={m} className="kbd">
                      {m}
                    </span>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>

      <Card
        title="Từ điển thuật ngữ"
        description="Mỗi dòng một cặp “từ gốc = bản dịch” để giữ đúng tên riêng, kỹ năng, vật phẩm game trên cả Google/Bing và AI."
        headerRight={
          <Button
            variant="primary"
            onClick={async () => {
              const entries = parseGlossary(glossaryText);
              await onUpdateConfig({ translation_glossary: entries });
              toast(`Đã lưu ${entries.length} thuật ngữ`, "success");
            }}
          >
            <Save size={16} />
            Lưu từ điển
          </Button>
        }
      >
        <div className="stack-8">
          <textarea
            className="ui-textarea"
            rows={5}
            placeholder={"# Ví dụ:\nHollow Purple = Tử Thức\nHP = Máu"}
            value={glossaryText}
            onChange={(e) => setGlossaryText(e.target.value)}
          />
          <div className="row-8 field-hint">
            <BookOpen size={16} />
            <span>Tối đa 200 thuật ngữ. Dòng bắt đầu bằng # là ghi chú.</span>
          </div>
        </div>
      </Card>

      <Dialog
        open={dialogOpen}
        title={editing ? "Sửa nhà cung cấp tùy chỉnh" : "Thêm nhà cung cấp tùy chỉnh"}
        onClose={() => setDialogOpen(false)}
        footer={
          <>
            <Button variant="secondary" onClick={() => setDialogOpen(false)}>
              Hủy
            </Button>
            <Button variant="primary" onClick={saveCustomProvider}>
              Lưu
            </Button>
          </>
        }
      >
        <div className="stack-12">
          <div className="stack-8">
            <label className="field-label">Tên hiển thị</label>
            <input
              className="ui-input"
              placeholder="vd: OpenRouter"
              value={cpName}
              onChange={(e) => setCpName(e.target.value)}
            />
          </div>
          <div className="stack-8">
            <label className="field-label">Endpoint (/v1)</label>
            <input
              className="ui-input"
              placeholder="https://openrouter.ai/api/v1"
              value={cpEndpoint}
              onChange={(e) => setCpEndpoint(e.target.value)}
            />
          </div>
          <div className="stack-8">
            <label className="field-label">API Key</label>
            <input
              type="password"
              className="ui-input"
              placeholder="sk-…"
              value={cpKey}
              onChange={(e) => setCpKey(e.target.value)}
            />
          </div>
          <div className="stack-8">
            <label className="field-label">Danh sách mô hình (mỗi dòng hoặc cách bằng dấu phẩy)</label>
            <textarea
              className="ui-textarea"
              rows={3}
              placeholder={"anthropic/claude-sonnet-4\nopenai/gpt-5-mini"}
              value={cpModels}
              onChange={(e) => setCpModels(e.target.value)}
            />
          </div>
        </div>
      </Dialog>

      <ConfirmDialog
        open={Boolean(deleteTarget)}
        title={`Xoá nhà cung cấp "${deleteTarget?.name}"?`}
        message="Nhà cung cấp và danh sách mô hình của nó sẽ bị gỡ khỏi cấu hình."
        confirmLabel="Xoá"
        confirmVariant="danger"
        onCancel={() => setDeleteTarget(null)}
        onConfirm={async () => {
          if (!deleteTarget) return;
          const next = config.custom_providers.filter((p) => p.id !== deleteTarget.id);
          await onUpdateConfig({ custom_providers: next });
          setDeleteTarget(null);
          toast("Đã xoá nhà cung cấp tùy chỉnh", "info");
        }}
      />
    </div>
  );
}
