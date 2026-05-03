"use client";

import { motion, type Variants } from "framer-motion";
import type { ReactNode } from "react";

const EASE: [number, number, number, number] = [0.22, 1, 0.36, 1];

const containerVariants: Variants = {
  hidden: { opacity: 0 },
  show: {
    opacity: 1,
    transition: { staggerChildren: 0.06, delayChildren: 0.05 },
  },
};

const itemVariants: Variants = {
  hidden: { opacity: 0, y: 14 },
  show: {
    opacity: 1,
    y: 0,
    transition: { duration: 0.42, ease: EASE },
  },
};

type StaggerAs = "div" | "section" | "ul";

/** Wraps children with a stagger animation — pair each child with `<StaggerItem>`. */
export function Stagger({
  children,
  className,
  as = "div",
}: {
  children: ReactNode;
  className?: string;
  as?: StaggerAs;
}) {
  const variants = containerVariants;
  const common = {
    variants,
    initial: "hidden" as const,
    animate: "show" as const,
    className,
  };

  if (as === "section") {
    return <motion.section {...common}>{children}</motion.section>;
  }
  if (as === "ul") {
    return <motion.ul {...common}>{children}</motion.ul>;
  }
  return <motion.div {...common}>{children}</motion.div>;
}

export function StaggerItem({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <motion.div variants={itemVariants} className={className}>
      {children}
    </motion.div>
  );
}
