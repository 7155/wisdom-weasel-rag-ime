import { ArrowRight } from 'lucide-react';
import { memo } from 'react';
import type { PawAppId } from '../runtime/app-registry';
import { PawBrandMark } from './PawAppIcon';

/**
 * PawFieldLede — 项目场的开场白，桌面第一屏的主体。
 *
 * 第一屏原本只有两块相同的白色角落面板和一片空掉的中间。这里补上主体：一段
 * 说明这台机器是做什么的开场白，和唯一一个主动作。它与 Agent 首页共用同一套
 * 品牌语法（钴蓝短杠的眉标、重字重标题、标题里一处钴蓝 em），所以桌面和 App
 * 读起来是同一个产品，而不是两套设计。
 *
 * 边界：
 * - 只做导航，不持有任何状态、不发请求、不缓存任何进度。项目场是进入工作的
 *   入口，永远不是开始 Session 的前置条件（PROJECT.md 非目标）。
 * - 文案只说得出真实产品名词（Session、回执、记忆与知识、上下文），不写指标、
 *   不写连接状态、不替 Runtime 作任何声明。
 * - `data-paw-evidence-echo` 是留给双向证据链的接缝：轨迹节点 ↔ 条目页的来回
 *   落地后，这里是桌面上指向「上下文是怎么装配的」的那个入口，不必改结构。
 *
 * 样式：paw-os.css 拥有几何，paw-os-shell-migrated-v1.css 拥有着墨与雾面底。
 */
export const PawFieldLede = memo(function PawFieldLede({ onOpen }: { onOpen: (appId: PawAppId) => void }) {
  return (
    <div className="paw-field-lede" data-paw-evidence-echo="field-lede">
      <p className="paw-field-lede__mark">
        <PawBrandMark size={13} />
        <b className="paw-brand-wordmark">PAW</b>
        <span>项目场</span>
      </p>
      <h2 className="paw-field-lede__title">交给 Session <em>一件事</em>。</h2>
      <p className="paw-field-lede__copy">
        做完之后留下回执；被接受的那部分才进入记忆与知识，下一次工作从更短的上下文开始。
      </p>
      <button className="paw-field-lede__start" onClick={() => onOpen('agent')} type="button">
        开始一件事<ArrowRight aria-hidden="true" size={15} />
      </button>
    </div>
  );
});
