import { Link } from "@tanstack/react-router"

import { cn } from "@/lib/utils"

interface LogoProps {
  variant?: "full" | "icon" | "responsive"
  className?: string
  asLink?: boolean
}

export function Logo({
  variant = "full",
  className,
  asLink = true,
}: LogoProps) {
  const content = (
    <span className={cn("inline-flex items-center gap-2", className)}>
      <img
        src="/assets/images/agtrack.png"
        alt={variant === "icon" ? "AgTrack" : ""}
        className={variant === "full" ? "size-9" : "size-5"}
      />
      {variant !== "icon" && (
        <span
          className={cn(
            "text-xl font-bold",
            variant === "responsive" && "group-data-[collapsible=icon]:sr-only",
          )}
        >
          AgTrack
        </span>
      )}
    </span>
  )

  return asLink ? <Link to="/dashboard">{content}</Link> : content
}
