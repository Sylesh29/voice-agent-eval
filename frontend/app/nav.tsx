"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  ["/", "Runs"],
  ["/compare", "Compare"],
  ["/patterns", "Failure patterns"],
  ["/calibration", "Evaluator calibration"],
];

export default function Nav() {
  const path = usePathname();
  return (
    <div className="top">
      <div className="wrap">
        <Link href="/" className="brand">
          Kyron Eval <span>/ voice agent</span>
        </Link>
        <div className="nav">
          {LINKS.map(([href, label]) => (
            <Link key={href} href={href}
                  className={path === href ? "on" : ""}>{label}</Link>
          ))}
        </div>
      </div>
    </div>
  );
}
