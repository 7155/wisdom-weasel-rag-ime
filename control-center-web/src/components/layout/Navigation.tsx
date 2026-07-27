import { Activity, Menu as MenuIcon, PanelLeftClose, PanelLeftOpen } from 'lucide-react';
import { useState } from 'react';
import {
  routeGroupLabels,
  routeRegistry,
  type RouteDefinition,
  type RouteId,
} from '@/app/route-registry';
import { prefetchRoute } from '@/app/router';
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
import type { ProductIdentity } from '@/features/identity/product-identity';
import { routeIcons } from './route-icons';

const mobilePrimaryRoutes: RouteId[] = ['agent', 'rooms', 'planning', 'memory'];

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
      onFocus={() => prefetchRoute(route.id)}
      onPointerEnter={() => prefetchRoute(route.id)}
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
  identity,
  onCollapsedChange,
}: {
  activeRouteId: RouteId;
  collapsed: boolean;
  identity: ProductIdentity;
  onCollapsedChange: (collapsed: boolean) => void;
}) {
  return (
    <aside className="shell-sidebar" aria-label="主导航">
      <div className="shell-brand">
        <span className="shell-brand__signal" role="img" aria-label={`${identity.productName}，本地运行`}>
          <Activity size={18} strokeWidth={1.8} aria-hidden="true" />
          <i aria-hidden="true" />
        </span>
        <span className="shell-brand__copy">
          <strong>{identity.productName}</strong>
          <small>{identity.tagline}</small>
        </span>
      </div>
      <nav className="shell-nav">
        {(Object.keys(routeGroupLabels) as Array<keyof typeof routeGroupLabels>).map((group) => (
          <section className="shell-nav__group" key={group} aria-label={routeGroupLabels[group]}>
            <p className="shell-nav__group-label">{routeGroupLabels[group]}</p>
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
          <span>只在本机</span>
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
          <DialogTitle>去哪里？</DialogTitle>
          <DialogDescription>对话、记忆、协作与设置都在这里。</DialogDescription>
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
            onFocus={() => prefetchRoute(route.id)}
            onPointerEnter={() => prefetchRoute(route.id)}
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
