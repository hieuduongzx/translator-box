import { useEffect, useState, type Dispatch, type SetStateAction } from "react";

export interface PersistentStateOptions<T> {
  validate?: (value: unknown) => value is T;
  serialize?: (value: T) => string;
  deserialize?: (raw: string) => unknown;
}

function resolveInitial<T>(initial: T | (() => T)): T {
  return typeof initial === "function" ? (initial as () => T)() : initial;
}

/**
 * Lưu và khôi phục trạng thái giao diện bền vững trong localStorage
 * (sidebar thu gọn, trang/tab cuối, bộ lọc, sắp xếp, kích thước cột, tỷ lệ chia khung).
 * Đọc đồng bộ ngay lần render đầu tiên để không bị chớp giao diện.
 */
export function usePersistentState<T>(
  key: string,
  defaultValue: T | (() => T),
  options?: PersistentStateOptions<T>,
): [T, Dispatch<SetStateAction<T>>] {
  const serialize = options?.serialize ?? JSON.stringify;
  const deserialize = options?.deserialize ?? JSON.parse;
  const validate = options?.validate;

  const [value, setValue] = useState<T>(() => {
    try {
      const raw = localStorage.getItem(key);
      if (raw !== null) {
        const parsed = deserialize(raw);
        if (!validate || validate(parsed)) {
          return parsed as T;
        }
      }
    } catch {
      // Bỏ qua lỗi đọc hoặc JSON hỏng, quay về giá trị mặc định
    }
    return resolveInitial(defaultValue);
  });

  useEffect(() => {
    try {
      localStorage.setItem(key, serialize(value));
    } catch {
      // Bỏ qua lỗi đầy bộ nhớ hoặc chế độ hạn chế storage
    }
  }, [key, value, serialize]);

  return [value, setValue];
}
