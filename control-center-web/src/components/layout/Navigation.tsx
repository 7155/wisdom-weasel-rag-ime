import { Menu as MenuIcon, PanelLeftClose, PanelLeftOpen } from 'lucide-react';
import { useState } from 'react';
import { routeRegistry, type RouteDefinition, type RouteId } from '@/app/route-registry';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
  IconButton,
  Tooltip,
} from '@/components/primitives';
import { routeIcons } from './route-icons';

const groupLabels = {
  work: '工作台',
  capability: '能力与知识',
  operations: '治理与系统',
} as const;

const mobilePrimaryRoutes: RouteId[] = ['planning', 'agent', 'rooms', 'roles'];

function RouteLink({
  compact = false,
  onNavigate,
  route,
  selected,
}: {
  compact?: boolean;
  onNavigate?: () => void;
  route: RouteDefinition;
  selected: boolean;
}) {
  const Icon = routeIcons[route.id];
  const anchor = (
    <a
      className="shell-nav__link"
      data-route={route.id}
      href={`#${route.path}`}
      aria-current={selected ? 'page' : undefined}
      onClick={onNavigate}
      title={route.label}
    >
      <Icon size={17} strokeWidth={1.9} aria-hidden="true" />
      <span>{route.label}</span>
    </a>
  );

  return compact ? (
    <Tooltip content={route.label} side="right">
      {anchor}
    </Tooltip>
  ) : anchor;
}

export function DesktopNavigation({
  activeRouteId,
  collapsed,
  onCollapsedChange,
}: {
  activeRouteId: RouteId;
  collapsed: boolean;
  onCollapsedChange: (collapsed: boolean) => void;
}) {
  return (
    <aside className="shell-sidebar" aria-label="主导航">
      <div className="shell-brand">
        <img
          className="shell-brand__mark"
          src="./companions/RagImeCompanionIdle.png"
          alt=""
          aria-hidden="true"
        />
        <span className="shell-brand__copy">
          <strong>智鼬</strong>
          <small>RAG IME CONTROL</small>
        </span>
      </div>
      <nav className="shell-nav">
        {(Object.keys(groupLabels) as Array<keyof typeof groupLabels>).map((group) => (
          <section className="shell-nav__group" key={group} aria-label={groupLabels[group]}>
            <p className="shell-nav__group-label">{groupLabels[group]}</p>
            {routeRegistry.filter((route) => route.group === group).map((route) => (
              <RouteLink
                compact={collapsed}
                key={route.id}
                route={route}
                selected={route.id === activeRouteId}
              />
            ))}
          </section>
        ))}
      </nav>
      <div className="shell-sidebar__footer">
        <span className="shell-sidebar__environment">
          <i aria-hidden="true" />
          <span>LOCAL</span>
        </span>
        <IconButton
          className="shell-sidebar__collapse"
          icon={collapsed ? <PanelLeftOpen size={17} /> : <PanelLeftClose size={17} />}
          label={collapsed ? '展开侧边栏' : '收起侧边栏'}
          onClick={() => onCollapsedChange(!collapsed)}
          tooltip
          tooltipSide="right"
        />
      </div>
    </aside>
  );
}

export function MobileRouteMenu({ activeRouteId }: { activeRouteId: RouteId }) {
  const [open, setOpen] = useState(false);
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <IconButton className="shell-mobile-menu__trigger" icon={<MenuIcon size={18} />} label="打开全部导航" />
      </DialogTrigger>
      <DialogContent className="shell-mobile-menu">
        <DialogHeader>
          <DialogTitle>控制中心</DialogTitle>
          <DialogDescription>本机控制台 · {routeRegistry.length} 个工作区</DialogDescription>
        </DialogHeader>
        <nav className="shell-mobile-menu__routes" aria-label="全部导航">
          {routeRegistry.map((route) => (
            <RouteLink
              key={route.id}
              onNavigate={() => setOpen(false)}
              route={route}
              selected={route.id === activeRouteId}
            />
          ))}
        </nav>
      </DialogContent>
    </Dialog>
  );
}

export function MobileBottomNavigation({ activeRouteId }: { activeRouteId: RouteId }) {
  return (
    <nav className="shell-mobile-nav" aria-label="快捷导航">
      {mobilePrimaryRoutes.map((routeId) => {
        const route = routeRegistry.find((item) => item.id === routeId)!;
        const Icon = routeIcons[routeId];
        return (
          <a
            key={routeId}
            className="shell-mobile-nav__link"
            href={`#${route.path}`}
            aria-current={routeId === activeRouteId ? 'page' : undefined}
          >
            <Icon size={19} strokeWidth={1.9} aria-hidden="true" />
            <span>{route.shortLabel}</span>
          </a>
        );
      })}
      <MobileRouteMenu activeRouteId={activeRouteId} />
    </nav>
  );
}
