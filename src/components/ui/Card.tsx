import type { ReactNode } from "react";

export interface CardProps {
  title?: string;
  description?: string;
  headerRight?: ReactNode;
  children: ReactNode;
  className?: string;
}

export function Card({ title, description, headerRight, children, className = "" }: CardProps) {
  return (
    <section className={`ui-card ${className}`.trim()}>
      {(title || description || headerRight) && (
        <div className="ui-card-header">
          <div>
            {title && <h2 className="ui-card-title">{title}</h2>}
            {description && <p className="ui-card-desc">{description}</p>}
          </div>
          {headerRight}
        </div>
      )}
      {children}
    </section>
  );
}
