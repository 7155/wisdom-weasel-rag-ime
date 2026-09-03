import {
  ArrowDownRight,
  ArrowUpRight,
  Ban,
  Brain,
  Check,
  Clock3,
  FileCheck2,
  GitMerge,
  FlaskConical,
  LockKeyhole,
  Network,
  SearchCheck,
  ShieldCheck,
  Target,
  Wrench,
} from 'lucide-react';
import type { CSSProperties, ReactNode } from 'react';
import {
  cacheTurns,
  cloudOpsComparison,
  duration,
  evidenceFiles,
  metricTransition,
  percent,
  relativeImprovement,
  retrievalMetrics,
  signedPercent,
  traceDefects,
} from './report-data';
import './evolution-report.css';

const sections = [
  ['origin', '为什么做 PAW'],
  ['primer', '先看原理'],
  ['rag', 'RAG 检索'],
  ['cloudops', 'CloudOps'],
  ['trace', 'Trace 闭环'],
  ['app', 'App 沙盒'],
  ['cache', '缓存'],
  ['evidence', '证据'],
] as const;

export function EvolutionReportFeature() {
  return (
    <main
      className="evolution-report"
      data-report-surface="standalone"
      data-route-id="evolution-report"
    >
      <header className="evolution-report__header">
        <div className="evolution-report__title-row">
          <div>
            <h1>自我进化实验账本</h1>
            <p className="evolution-report__lede">
              <strong>这不是成绩单</strong>
              <span>它回答每个数字怎么得到、为什么 Keep 或 Reject，以及哪些结论仍然不能说。</span>
            </p>
          </div>
          <div className="evolution-report__snapshot" aria-label="证据快照">
            <span>证据快照</span>
            <strong>2026-09-01</strong>
          </div>
        </div>

        <div className="evolution-report__gate" aria-label="实验晋升流程">
          <GateStep icon={<FlaskConical size={17} />} label="冻结输入与配置" />
          <GateStep icon={<SearchCheck size={17} />} label="同组 Validation" />
          <GateStep icon={<ShieldCheck size={17} />} label="规则门禁" />
          <GateStep icon={<Check size={17} />} label="Keep 或 Reject" />
          <GateStep icon={<LockKeyhole size={17} />} label="Held-out 仍封存" muted />
        </div>
      </header>

      <nav className="evolution-report__toc" aria-label="报告章节">
        {sections.map(([id, label]) => (
          <button key={id} onClick={() => scrollToReportSection(id)} type="button">{label}</button>
        ))}
      </nav>

      <div className="evolution-report__body">
        <ReportSection
          id="origin"
          index="项目出发点"
          title="为什么要做这一套 Agent 工作台"
          summary="大型代码项目里，问题通常不是模型不会写代码，而是它会忘记上下文、误解需求、反复打补丁，并在多轮修改后失去整体方向。"
        >
          <div className="evolution-report__origin-grid">
            <OriginItem
              icon={<Brain size={19} />}
              title="上下文丢失"
              problem="对话压缩后，Agent 忘了原始需求、计划和之前的决策。"
              solution="用 AGENTS.md 做导航，把 Agent 专属 Docs、Plan、进度、产出和验收结果持久化；每次需要时按索引重新读取。"
            />
            <OriginItem
              icon={<Target size={19} />}
              title="需求不明确"
              problem="一句‘优化一下’会被不同 Agent 解释成不同目标。"
              solution="开工前做树状澄清，记录目标、约束、分支和验收条件；结束时回对原始需求，而不是只看 Plan 是否完成。"
            />
            <OriginItem
              icon={<Wrench size={19} />}
              title="不断打补丁"
              problem="模型只修眼前症状，Bug A 修完又出现 Bug B。"
              solution="用 Skill、专项测试、Trace 和进度检查约束过程；同时承认工作流不能替代更强模型，长期无进展就停止、拆分或升级。"
            />
            <OriginItem
              icon={<Network size={19} />}
              title="缺少整体设计"
              problem="局部修复可能破坏 Session、Room、Tool 和恢复之间的边界。"
              solution="明确 Pi、Room、Memory/RAG、Adapter 和 Control Center 的唯一 owner，禁止 UI 或 Room 再造第二套 Runtime。"
            />
            <OriginItem
              icon={<GitMerge size={19} />}
              title="多轮修改冲突"
              problem="多个 Agent 按各自 Plan 并行修改，最后互相覆盖，人的角色变成中转站。"
              solution="让执行、评估、调参分工，通过共享文档和接口合同交接，由一个 Root 汇总；并行的是工作，不是最终状态所有权。"
            />
          </div>
          <Boundary>这些机制让错误可被发现、停止、恢复和复核，但不能声称 Agent 从此不会犯错。</Boundary>
        </ReportSection>
        <ReportSection
          id="primer"
          index="从零开始"
          title="先理解：系统到底在做什么"
          summary="PAW 不是让一个模型边改边给自己打分，而是把提出方案、受控实验、评分和晋升拆开，让失败也留下证据。"
        >
          <div className="evolution-report__plain-language">
            <h3>RAG 是“先找资料，再回答”</h3>
            <p>
              普通模型只靠当前上下文和训练记忆。RAG 会先从指定知识库找出相关片段，再把片段连同问题交给模型。
              所以它至少有两层质量：<strong>资料有没有找对</strong>，以及<strong>最终回答有没有忠实使用资料</strong>。
            </p>
          </div>

          <ol className="evolution-report__roles" aria-label="RAG 自我优化角色">
            <li>
              <span>提出候选</span>
              <div><strong>调参 Agent</strong><p>改变 chunk、检索、融合、重排或工作流参数；它只提方案，不给自己判分。</p></div>
            </li>
            <li>
              <span>受控运行</span>
              <div><strong>沙盒测试 Agent</strong><p>在临时隔离工作区运行同一冻结数据集，不写生产数据，也不偷看 Held-out。</p></div>
            </li>
            <li>
              <span>独立评分</span>
              <div><strong>评价 Agent</strong><p>按确定性答案、事实证据和必要的 AI Judge 维度评分；原始结果不能被候选改写。</p></div>
            </li>
            <li>
              <span>决定去留</span>
              <div><strong>Keep / Reject 门禁</strong><p>同时检查质量、成本、身份和证据。某个指标变好，不代表候选自动晋升。</p></div>
            </li>
          </ol>

          <div className="evolution-report__glossary" aria-label="指标白话解释">
            <div><strong>Validation 是反复练习用的验证集</strong><span>调参期间可以多次运行，用来比较候选；它不是最终考试。</span></div>
            <div><strong>Held-out 是一次性最终考试</strong><span>调参和选候选时不能查看，只有满足晋升条件后才能开启。</span></div>
            <div><strong>canary 是小范围机制探针</strong><span>先用极小、隔离的样本确认机制真的工作，不能代表生产平均表现。</span></div>
            <div><strong>Provider cache 是模型服务端复用前缀</strong><span>cacheRead 是 Provider 明确报告的已复用 token 数，不是本地估算。</span></div>
            <div><strong>nDCG@10 看排序质量</strong><span>正确资料越靠前、重要资料顺序越合理，分数越高。</span></div>
            <div><strong>MRR 看第一个正确答案有多靠前</strong><span>第一条正确结果越早出现，分数越高。</span></div>
            <div><strong>Recall@10 看前十条找回了多少应找资料</strong><span>应该找到的资料里，有多少进入了前十。</span></div>
            <div><strong>CA 看第一答案是否整体正确</strong><span>12 个冻结用例中，第一答案满足标准结果的比例。</span></div>
            <div><strong>JRA 看联合根因是否正确</strong><span>故障对象与关联根因需要同时匹配；Top-3 JRA 则允许正确联合答案出现在前三个候选里。</span></div>
            <div><strong>SGG 是本项目的一题固定离线夹具</strong><span>它模拟销售台账问答，只用于验证链路，不是公开榜单或真实业务数据。</span></div>
            <div><strong>binding digest 是绑定指纹</strong><span>App、Package、Skill 和测试套件内容共同生成；任一内容变化，指纹就不匹配。</span></div>
            <div><strong>Precision / Recall / F1 是命中质量</strong><span>Precision 看命中是否准确，Recall 看该找的是否找全，F1 综合两者。</span></div>
            <div><strong>manifest 是版本与资源清单</strong><span>记录包的身份、版本、权限和文件；hash 是内容指纹，用来证明前后是否同一份。</span></div>
            <div><strong>loopback 是只在本机通信</strong><span>Tool 通过 127.0.0.1 和 capability token 访问，不直接暴露到外网。</span></div>
            <div><strong>Trace 是实验飞行记录器</strong><span>把模型、Tool、时间、失败和证据串起来，帮助定位为什么成功或失败。</span></div>
          </div>

          <table className="evolution-report__before-after">
            <caption>这轮把自我优化流程从什么状态改到了什么状态</caption>
            <thead><tr><th>环节</th><th>以前</th><th>现在</th></tr></thead>
            <tbody>
              <tr><th>实验身份</th><td>模型、Prompt、数据版本可能说不清</td><td>provider / model / thinking / suite / manifest 全部冻结并 hash</td></tr>
              <tr><th>失败记录</th><td>重试可能覆盖上一轮失败</td><td>attempt append-only，失败和恢复分别留收据</td></tr>
              <tr><th>答案证据</th><td>有引用或词面重合就可能得分</td><td>逐事实绑定来源、chunk 与原文；拒答单独计算</td></tr>
              <tr><th>候选晋升</th><td>局部变好容易被当作整体优化</td><td>质量、成本和边界共同判定 Keep / Reject，Held-out 一次性开启</td></tr>
            </tbody>
          </table>
        </ReportSection>

        <ReportSection
          id="rag"
          index="检索质量"
          title="RAG 检索调优"
          summary="同一份 16 题切片上比较 14 个配置，混合检索加重排明显超过词法 floor；但回答引用质量仍未过门。"
        >
          <div className="evolution-report__fact-line" aria-label="RAG 试验规模">
            <strong>16 个 Validation query</strong>
            <span>×</span>
            <strong>14 个候选配置</strong>
            <ScopeTag>Validation-only</ScopeTag>
            <ScopeTag tone="locked">Held-out 未打开</ScopeTag>
          </div>

          <figure className="evolution-report__comparison" aria-labelledby="rag-comparison-title">
            <figcaption id="rag-comparison-title">词法 floor 与入选候选的同组对比</figcaption>
            <div className="evolution-report__comparison-head" aria-hidden="true">
              <span>指标</span><span>原始数值</span><span>相对变化</span>
            </div>
            {retrievalMetrics.map((metric) => {
              const delta = relativeImprovement(metric.baseline, metric.candidate);
              return (
                <div className="evolution-report__metric-row" key={metric.id}>
                  <strong>{metric.label}</strong>
                  <div className="evolution-report__metric-measure">
                    <span>{metricTransition(metric.baseline, metric.candidate)}</span>
                    <span className="evolution-report__bar" aria-hidden="true">
                      <i style={{ '--metric-width': `${metric.candidate * 100}%` } as CSSProperties} />
                    </span>
                  </div>
                  <b>{signedPercent(delta)}</b>
                </div>
              );
            })}
          </figure>

          <Equation>
            相对提升 =（候选 − 基线）÷ 基线。例如 nDCG：
            （0.887203 − 0.612801）÷ 0.612801 = 44.78%。
          </Equation>

          <ChangeLedger
            items={[
              ['以前', '词法检索作为 floor，相关片段排序和找回率偏低。'],
              ['改变', '在同一 16 题切片上冻结数据，比较 14 种混合检索与重排配置。'],
              ['效果', '三个检索指标分别相对提升 44.78%、43.53%、42.19%。'],
              ['判定', '选为 Validation 候选，但回答逐事实引用只有 2/9，因此未晋升。'],
            ]}
          />

          <div className="evolution-report__interpretation">
            <div>
              <h3>这说明什么</h3>
              <p>这组候选在冻结 Validation 切片上更会把相关片段排到前面，适合作为下一轮候选。</p>
            </div>
            <div>
              <h3>为什么还不能晋升</h3>
              <p>逐事实引用门禁只有 2/9。检索排序变好，不等于最终回答已经逐事实可证。</p>
            </div>
            <Boundary>不能写成生产提升、Held-out 通过或对所有企业语料都有效。</Boundary>
          </div>
        </ReportSection>

        <ReportSection
          id="cloudops"
          index="Agent 工作流"
          title="CloudOps 工作流试验"
          summary="基线跑通后，搜索优先候选更快、Top-3 更好，但首选正确率下降且 Tool 成本接近翻倍，所以门禁拒绝。"
        >
          <div className="evolution-report__baseline-strip">
            <div><span>基线完成</span><strong>12 / 12 回答</strong></div>
            <div><span>Tool 可靠性</span><strong>98 / 98 成功</strong></div>
            <div><span>CA</span><strong>1.0000</strong></div>
            <div><span>JRA</span><strong>0.8333</strong></div>
          </div>

          <div className="evolution-report__decision-grid">
            <div className="evolution-report__decision-copy">
              <span className="evolution-report__decision-label"><Ban size={17} /> Reject</span>
              <h3>更快，不代表更好</h3>
              <p>候选把两个漏掉的联合答案移进 Top-3，但第一答案的整体正确率下降，JRA 没有提升。</p>
              <ul>
                <li>CA：1.0000 → 0.8333</li>
                <li>JRA：0.8333 → 0.8333</li>
                <li>Top-3 JRA：0.8333 → 1.0000</li>
              </ul>
            </div>
            <table className="evolution-report__delta-table">
              <caption>基线与搜索优先候选</caption>
              <thead><tr><th>指标</th><th>基线</th><th>候选</th><th>变化</th></tr></thead>
              <tbody>
                <tr>
                  <th>耗时</th>
                  <td>{duration(cloudOpsComparison.baseline.elapsedMs)}</td>
                  <td>{duration(cloudOpsComparison.candidate.elapsedMs)}</td>
                  <td className="is-positive"><ArrowDownRight size={15} /> −26.58%</td>
                </tr>
                <tr>
                  <th>Tool calls</th>
                  <td colSpan={2}>98 → 189</td>
                  <td className="is-negative"><ArrowUpRight size={15} /> +92.86%</td>
                </tr>
              </tbody>
            </table>
          </div>

          <div className="evolution-report__root-cause">
            <Wrench aria-hidden="true" size={19} />
            <div>
              <h3>Trace 看到的根因</h3>
              <p>搜索优先流程缺少“先定位故障对象，再查根因”的两阶段约束，也没有 search/list/重复读取的停止预算。</p>
            </div>
          </div>
          <Equation>
            Tool 增幅 =（189 − 98）÷ 98 = 92.86%；耗时降幅 =（1,356,582 − 996,035）÷ 1,356,582 = 26.58%。
            但 CA 从 1.0000 降到 0.8333，因此总体判定仍是 Reject。
          </Equation>
          <Boundary>候选未安装，Held-out 未查看；Top-3 改善不能抵消 CA 回退和 Tool 开销。</Boundary>
        </ReportSection>

        <ReportSection
          id="trace"
          index="缺陷与修复"
          title="Trace 缺陷闭环"
          summary="数字按唯一根因计数，重试次数和测试数量都不算缺陷；只有同时保留失败、修复与验证证据的根因才进入 8。"
        >
          <div className="evolution-report__trace-counts">
            <strong>8 个闭环缺陷</strong>
            <span>=</span>
            <b>3 个主仓 Validation</b>
            <span>+</span>
            <b>5 个源码候选复验</b>
            <small>另有 3 个源码/测试级修复，不计入 8</small>
          </div>

          <div className="evolution-report__defect-head" aria-hidden="true">
            <span>缺陷</span><span>以前的问题</span><span>改了什么</span><span>带来的效果</span>
          </div>
          <ol className="evolution-report__defect-list">
            {traceDefects.map((defect) => (
              <li key={defect.id}>
                <code>{defect.id}</code>
                <span>{defect.problem}</span>
                <span>{defect.change}</span>
                <span>{defect.effect}</span>
              </li>
            ))}
          </ol>

          <div className="evolution-report__secondary-changes">
            <h3>另外 3 个源码/测试级修复为什么没有计入 8</h3>
            <ul>
              <li>RAG Tool envelope 接受并只保留 sourceLoopId 的 hash，避免公开原始标识。</li>
              <li>Skill 增加“合成后再检查未覆盖事实”的有限检索预算；结构已修，但回答质量仍待复验。</li>
              <li>无 Tool critic 与父级补充检索契约对齐；真实 Agentic 终态仍未完整，因此不升级成闭环缺陷。</li>
            </ul>
          </div>

          <div className="evolution-report__overlap-note">
            <FileCheck2 aria-hidden="true" size={18} />
            <p><strong>3 个 Skill 问题、5 个工作流改进、6 个 Tool/Runtime 契约改进。</strong>这些分类互有重叠，不能相加。</p>
          </div>
          <Boundary>不能写成 Trace Agent 自动修复了全部 8 个问题；其中 5 个是未安装源码候选的复验证据。</Boundary>
        </ReportSection>

        <ReportSection
          id="app"
          index="自举 App"
          title="掌柜问数沙盒"
          summary="这里验证的是“App 源码、Pi Package、专属 Skill、沙盒和收据能否绑定”，不是生产经营问答准确率。"
        >
          <div className="evolution-report__app-flow" aria-label="掌柜问数沙盒验证流程">
            <FlowNode title="故障注入" detail="故意写错 binding digest" status="failed" />
            <span aria-hidden="true">→</span>
            <FlowNode title="Fail closed" detail="沙盒未执行" status="failed" />
            <span aria-hidden="true">→</span>
            <FlowNode title="原位修复" detail="恢复同版本精确 digest" />
            <span aria-hidden="true">→</span>
            <FlowNode title="沙盒复验" detail="Trace / Eval / Sandbox 已关联" status="passed" />
          </div>

          <dl className="evolution-report__app-facts">
            <div><dt>固定数据</dt><dd>1 个 SGG 固定夹具</dd></div>
            <div><dt>确定性结果</dt><dd>Precision / Recall / F1 = 1.0</dd></div>
            <div><dt>模型调用</dt><dd>Provider 调用 0</dd></div>
            <div><dt>隔离</dt><dd>网络阻断、生产写入阻断</dd></div>
            <div><dt>前端</dt><dd>8 项聚焦测试 + production build</dd></div>
            <div><dt>下一边界</dt><dd>Spider 2.0-Lite 未正式评分</dd></div>
          </dl>
          <ChangeLedger
            items={[
              ['以前', '源码、Package、Skill 与 SGG 套件可能看似同版本，实际内容已经漂移。'],
              ['改变', '用 binding digest 把四者绑定；故意制造错指纹，确认沙盒在执行前 fail closed。'],
              ['效果', '恢复同版本精确指纹后，1 个固定夹具得到关联的 Trace / Eval / Sandbox 收据。'],
              ['判定', 'Sandbox verified source candidate；这份快照本身不证明安装或生产准确率。'],
            ]}
          />
          <Boundary>不能写成生产 Text-to-SQL 准确率；547 个问题和 256 条 gold SQL 只有本地源，缺少执行数据库。</Boundary>
        </ReportSection>

        <ReportSection
          id="cache"
          index="上下文效率"
          title="上下文缓存 canary"
          summary="同一稳定系统前缀连续请求，观察 Provider 明确返回的 cacheRead；再改变前缀，确认命中消失。"
        >
          <table className="evolution-report__cache-table">
            <caption>Provider 上报的逐轮 token</caption>
            <thead><tr><th>轮次</th><th>未缓存输入</th><th>cacheRead</th><th>相对冷轮</th></tr></thead>
            <tbody>
              {cacheTurns.map((turn) => (
                <tr key={turn.label}>
                  <th>{turn.label}</th>
                  <td>{turn.inputTokens.toLocaleString('en-US')}</td>
                  <td>{turn.cacheReadTokens.toLocaleString('en-US')}</td>
                  <td>{turn.reduction === null ? '—' : percent(turn.reduction)}</td>
                </tr>
              ))}
            </tbody>
          </table>

          <div className="evolution-report__correction">
            <Clock3 aria-hidden="true" size={18} />
            <div>
              <h3>正确结论：90.96%–91.16%</h3>
              <p>冷轮 10,647 token，热轮分别为 941 和 963；上一版摘要中的 92.7%–92.9% 是抄录错误，本页按原始 token 重新计算。</p>
            </div>
          </div>
          <ChangeLedger
            items={[
              ['以前', '每轮请求都可能重复发送几乎相同的系统前缀，无法确认 Provider 是否复用。'],
              ['改变', '冻结同一系统前缀跑冷轮和两次热轮，再用改变前缀的对照组验证失效。'],
              ['效果', '两次热轮各有 9,728 个 cacheRead token；对照组重新变为 0。'],
              ['判定', 'canary passed；只证明稳定前缀缓存机制，不代表生产总成本或延迟。'],
            ]}
          />
          <Boundary>这是隔离 canary 的未缓存输入降幅，不是总成本、端到端延迟或生产平均节省。</Boundary>
        </ReportSection>

        <ReportSection
          id="evidence"
          index="可追溯性"
          title="证据文件"
          summary="页面只做阅读投影；下面这些收据与账本才是数字的权威来源。"
        >
          <ul className="evolution-report__evidence-list">
            {evidenceFiles.map(([label, file]) => (
              <li key={file}><span>{label}</span><code>{file}</code></li>
            ))}
          </ul>
          <p className="evolution-report__footnote">
            Validation、沙盒、安装和真实前台是不同证据等级；页面不会把其中一种自动升级成另一种。
          </p>
        </ReportSection>
      </div>
    </main>
  );
}

function scrollToReportSection(id: string) {
  const section = document.getElementById(id);
  if (!section) return;
  const scrollOwner = section.closest<HTMLElement>('.paw-system-app__page');
  if (!scrollOwner) {
    section.scrollIntoView({ behavior: 'auto', block: 'start' });
    return;
  }
  const top = scrollOwner.scrollTop
    + section.getBoundingClientRect().top
    - scrollOwner.getBoundingClientRect().top;
  scrollOwner.scrollTo({ behavior: 'auto', top: Math.max(0, top) });
}

function GateStep({ icon, label, muted = false }: { icon: ReactNode; label: string; muted?: boolean }) {
  return <span className="evolution-report__gate-step" data-muted={muted || undefined}>{icon}{label}</span>;
}

function ScopeTag({ children, tone = 'default' }: { children: ReactNode; tone?: 'default' | 'locked' }) {
  return <span className="evolution-report__scope-tag" data-tone={tone}>{children}</span>;
}

function OriginItem({
  icon,
  problem,
  solution,
  title,
}: {
  icon: ReactNode;
  problem: string;
  solution: string;
  title: string;
}) {
  return (
    <article className="evolution-report__origin-item">
      <div className="evolution-report__origin-title"><span>{icon}</span><h3>{title}</h3></div>
      <p><strong>问题</strong>{problem}</p>
      <p><strong>怎么解决</strong>{solution}</p>
    </article>
  );
}

function ReportSection({
  children,
  id,
  index,
  summary,
  title,
}: {
  children: ReactNode;
  id: string;
  index: string;
  summary: string;
  title: string;
}) {
  const headingId = `${id}-heading`;
  return (
    <section aria-labelledby={headingId} className="evolution-report__section" id={id} role="region">
      <header className="evolution-report__section-head">
        <span>{index}</span>
        <div>
          <h2 id={headingId}>{title}</h2>
          <p>{summary}</p>
        </div>
      </header>
      <div className="evolution-report__section-body">{children}</div>
    </section>
  );
}

function Equation({ children }: { children: ReactNode }) {
  return <p className="evolution-report__equation"><span>计算</span>{children}</p>;
}

function Boundary({ children }: { children: ReactNode }) {
  return <p className="evolution-report__boundary"><Ban aria-hidden="true" size={16} />{children}</p>;
}

function ChangeLedger({ items }: { items: ReadonlyArray<readonly [string, string]> }) {
  return (
    <dl className="evolution-report__change-ledger">
      {items.map(([label, detail]) => <div key={label}><dt>{label}</dt><dd>{detail}</dd></div>)}
    </dl>
  );
}

function FlowNode({
  detail,
  status = 'neutral',
  title,
}: {
  detail: string;
  status?: 'neutral' | 'failed' | 'passed';
  title: string;
}) {
  return <div className="evolution-report__flow-node" data-status={status}><strong>{title}</strong><span>{detail}</span></div>;
}
