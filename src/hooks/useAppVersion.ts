import { useEffect, useState } from "react";
import { getVersion } from "@tauri-apps/api/app";

let cachedVersion: string | null = null;
let pendingRequest: Promise<string> | null = null;

function fetchVersionOnce(): Promise<string> {
  if (cachedVersion !== null) {
    return Promise.resolve(cachedVersion);
  }
  if (!pendingRequest) {
    pendingRequest = getVersion()
      .then((ver) => {
        cachedVersion = ver;
        return ver;
      })
      .catch(() => "");
  }
  return pendingRequest;
}

/**
 * Lấy số phiên bản trực tiếp từ Tauri `getVersion()` (không bao giờ ghi cứng trong frontend).
 * Trả về chuỗi rỗng trong lúc đang tải hoặc khi chạy preview ngoài Tauri.
 */
export function useAppVersion(): string {
  const [version, setVersion] = useState<string>(() => cachedVersion ?? "");

  useEffect(() => {
    let active = true;
    fetchVersionOnce().then((ver) => {
      if (active && ver) {
        setVersion(ver);
      }
    });
    return () => {
      active = false;
    };
  }, []);

  return version;
}
