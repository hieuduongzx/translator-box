import type { HTMLAttributes, ReactNode } from "react";

export interface CardProps extends Omit<HTMLAttributes<HTMLDivElement>, "title"> {
  title?: ReactNode;
  description?: ReactNode;
  headerRight?: ReactNode;
  flush?: boolean;
  children?: ReactNode;
}

export function Card({
  title,
  description,
  headerRight,
  flush = false,
  className = "",
  children,
  ...rest
}: CardProps) {
  const classes = ["ui-card", flush ? "ui-card-flush" : "", className]
    .filter(Boolean)
    .join(" ");

  return (
    <div className={classes} {...rest}>
      {(title || description || headerRight) && (
        <div className="ui-card-header">
          <div>
            {title && <h3 className="ui-card-title">{title}</h3>}
            {description && <p className="ui-card-desc">{description}</p>}
          </div>
          {headerRight}
        </div>
      )}
      {children}
    </div>
  );
}
