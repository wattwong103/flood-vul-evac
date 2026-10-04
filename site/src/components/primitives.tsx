/**
 * Shared presentational primitives.
 *
 * These carry the product rules: every number is stamped with its validation
 * status and model time, a missing value renders as "not available" rather
 * than zero, and every status has a non-colour cue.
 */

import type { ReactNode } from "react";
import { CircleAlert, CircleDashed, Loader2, RefreshCw, ShieldAlert } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/client";
import {
  isValidationStatus,
  VALIDATION_STATUS_NOTE,
  type ValidationStatus,
} from "@/lib/api";
import { formatTimestamp, NOT_AVAILABLE, NOT_COMPUTED } from "@/lib/format";

/* ------------------------------------------------------------------ *
 * Validation status
 * ------------------------------------------------------------------ */

export function resolveValidationStatus(value: unknown): ValidationStatus | null {
  return isValidationStatus(value) ? value : null;
}

/**
 * The stamp that must accompany every number on the site: what the run's
 * validation status is, and when in the model the number was produced.
 */
export function ValidationStamp({
  status,
  modelTime,
  compact = false,
}: {
  status: string | null | undefined;
  modelTime: string | null;
  compact?: boolean;
}) {
  const resolved = resolveValidationStatus(status);
  return (
    <p className={`validation-stamp${compact ? " compact" : ""}`}>
      <Badge
        variant="outline"
        className={`status-badge status-${resolved ?? "unknown"}`}
      >
        <span aria-hidden="true" className="status-glyph">
          {resolved ? "◆" : "○"}
        </span>
        {resolved ?? "validation status not reported"}
      </Badge>
      <span className="stamp-time">
        model time {modelTime ?? NOT_AVAILABLE}
      </span>
    </p>
  );
}

/** A one-line explanation of what the current status permits. */
export function ValidationStatusNote({ status }: { status: string | null | undefined }) {
  const resolved = resolveValidationStatus(status);
  return (
    <p className="status-note">
      <ShieldAlert size={15} aria-hidden="true" />
      <span>
        {resolved
          ? VALIDATION_STATUS_NOTE[resolved]
          : "The API did not report a validation status for this run, so no claim about fitness for use can be made."}
      </span>
    </p>
  );
}

/* ------------------------------------------------------------------ *
 * States: loading, missing, error
 * ------------------------------------------------------------------ */

export function LoadingState({ label }: { label: string }) {
  return (
    <div className="state-block" role="status" aria-live="polite">
      <Loader2 className="spin" size={18} aria-hidden="true" />
      <span>{label}</span>
    </div>
  );
}

export function NoRunState({
  what = "results",
  detail,
  onReload,
}: {
  what?: string;
  detail?: ReactNode;
  onReload?: () => void;
}) {
  return (
    <div className="state-block empty" role="status">
      <CircleDashed size={22} aria-hidden="true" />
      <div>
        <strong>No completed run yet.</strong>
        <p>
          The API has not published a completed run, so there are no {what} to show.
          This screen will not display placeholder or zero values.
        </p>
        {detail}
      </div>
      {onReload ? (
        <Button variant="outline" size="sm" onClick={onReload}>
          <RefreshCw size={14} aria-hidden="true" /> Check again
        </Button>
      ) : null}
    </div>
  );
}

export function ErrorState({
  error,
  onRetry,
  context,
}: {
  error: ApiError;
  onRetry?: () => void;
  context?: string;
}) {
  const offline = error.isOffline;
  return (
    <div className="state-block error" role="alert">
      <CircleAlert size={22} aria-hidden="true" />
      <div>
        <strong>
          {offline ? "The API is not reachable." : "The API could not be read."}
        </strong>
        <p>{error.message}</p>
        {context ? <p className="muted">{context}</p> : null}
        {error.detail ? <p className="muted mono">API said: {error.detail}</p> : null}
      </div>
      {onRetry ? (
        <Button variant="outline" size="sm" onClick={onRetry}>
          <RefreshCw size={14} aria-hidden="true" /> Retry
        </Button>
      ) : null}
    </div>
  );
}

/* ------------------------------------------------------------------ *
 * Numbers
 * ------------------------------------------------------------------ */

export function MetricCard({
  label,
  value,
  unit,
  caption,
  quantity,
  status,
  modelTime,
  emphasis = false,
  icon,
}: {
  label: string;
  value: string;
  unit?: string | null;
  caption?: ReactNode;
  /** Names the exact population quantity, e.g. "people present". */
  quantity?: string;
  status: string | null | undefined;
  modelTime: string | null;
  emphasis?: boolean;
  icon?: ReactNode;
}) {
  const unavailable = value === NOT_AVAILABLE || value === NOT_COMPUTED;
  return (
    <Card className={`metric-card${emphasis ? " emphasis" : ""}`}>
      <CardHeader className="metric-head">
        <CardTitle className="metric-label">
          {icon ? (
            <span aria-hidden="true" className="metric-icon">
              {icon}
            </span>
          ) : null}
          {label}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <p className={`metric-value${unavailable ? " unavailable" : ""}`}>
          {value}
          {unavailable || !unit ? null : <span className="metric-unit">{unit}</span>}
        </p>
        {quantity ? <p className="metric-quantity">Quantity: {quantity}</p> : null}
        {caption ? <p className="metric-caption">{caption}</p> : null}
        <ValidationStamp status={status} modelTime={modelTime} compact />
      </CardContent>
    </Card>
  );
}

/* ------------------------------------------------------------------ *
 * Layout helpers
 * ------------------------------------------------------------------ */

export function PageIntro({
  kicker,
  title,
  lead,
  aside,
}: {
  kicker: string;
  title: ReactNode;
  lead?: ReactNode;
  aside?: ReactNode;
}) {
  return (
    <header className="page-intro">
      <div>
        <p className="eyebrow">{kicker}</p>
        <h1>{title}</h1>
        {lead ? <p className="lead">{lead}</p> : null}
      </div>
      {aside ? <div className="intro-aside">{aside}</div> : null}
    </header>
  );
}

export function Panel({
  title,
  description,
  actions,
  children,
  footer,
}: {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
}) {
  return (
    <Card className="panel">
      <CardHeader className="panel-head">
        <div>
          <CardTitle className="panel-title">{title}</CardTitle>
          {description ? <p className="panel-desc">{description}</p> : null}
        </div>
        {actions ? <div className="panel-actions">{actions}</div> : null}
      </CardHeader>
      <CardContent className="panel-body">{children}</CardContent>
      {footer ? <div className="panel-foot">{footer}</div> : null}
    </Card>
  );
}

export function RunStamp({ runId, createdAt }: { runId: string | null; createdAt: string | null }) {
  return (
    <p className="run-stamp">
      <span className="mono">run {runId ?? "none selected"}</span>
      <span>created {formatTimestamp(createdAt)}</span>
    </p>
  );
}
