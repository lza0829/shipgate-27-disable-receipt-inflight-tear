import React, { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import { AppStatusBadge, DisableLamp, FrozenBadge, LockedButton } from '../components/FreezeBadge'

export default function Disable() {
  const [overview, setOverview] = useState(null)
  const [appId, setAppId] = useState('')
  const [core, setCore] = useState(null)
  const [err, setErr] = useState('')
  const [msg, setMsg] = useState('')
  const [probe, setProbe] = useState('')
  const [releaseId, setReleaseId] = useState('')
  const [busy, setBusy] = useState(false)

  const loadOverview = async () => {
    const data = await api('/停用/总览')
    setOverview(data)
    const apps = data.应用核 || []
    if (!appId && apps[0]) setAppId(String(apps[0].应用编号))
    return data
  }

  const loadCore = async (id = appId) => {
    if (!id) return null
    const data = await api(`/应用/${id}/停用核`)
    setCore(data)
    const first = (data.在途发版 || [])[0]
    setReleaseId((current) => {
      const currentBelongs = (data.在途发版 || []).some(
        (r) => String(r.编号) === String(current),
      )
      if (current && currentBelongs) return String(current)
      return first ? String(first.编号) : ''
    })
    return data
  }

  useEffect(() => {
    loadOverview().catch((e) => setErr(e.message))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (appId) loadCore(appId).catch((e) => setErr(e.message))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [appId])

  const apps = overview?.应用核 || []
  const selected = useMemo(
    () => core || apps.find((a) => String(a.应用编号) === String(appId)) || null,
    [core, apps, appId],
  )

  const runDisable = async () => {
    setErr(''); setMsg(''); setBusy(true)
    try {
      const res = await api(`/应用/${appId}/停用`, {
        method: 'POST',
        body: JSON.stringify({ 备注: '停用页同核收口' }),
      })
      setCore(res)
      setMsg(`停用回执：${res.灯文案 || (res.干净 ? '停用干净' : '停用缺口')}；缺口 ${res.缺口数 ?? 0}`)
      await loadOverview()
    } catch (e) {
      let detail = e.message
      try {
        const parsed = JSON.parse(e.message)
        // api.js already unwraps FastAPI's `detail`; support both unwrapped
        // ({ message, 核 }) and raw ({ detail: { message, 核 } }) shapes.
        const rejectedCore = parsed?.核 || parsed?.detail?.核
        const rejectedMessage = parsed?.message || parsed?.detail?.message
        if (rejectedCore) {
          setCore(rejectedCore)
          detail = `同核校验退回：${rejectedCore.缺口数 ?? rejectedCore.gap_count ?? '?'} 个缺口`
        } else if (rejectedMessage) {
          detail = rejectedMessage
        }
      } catch { /* plain error */ }
      setErr(detail)
      await loadOverview().catch(() => {})
    } finally {
      setBusy(false)
    }
  }

  const heal = async () => {
    setErr(''); setMsg('')
    try {
      const res = await api(`/应用/${appId}/停用/收口`, { method: 'POST' })
      setCore(res)
      setMsg(res.收口动作 || '停用核已重放')
      await loadOverview()
    } catch (e) { setErr(e.message) }
  }

  const enable = async () => {
    setErr(''); setMsg('')
    try {
      await api(`/应用/${appId}`, { method: 'PATCH', body: JSON.stringify({ 状态: '启用' }) })
      setMsg('已恢复启用，停用推进冻结痕迹已收口重开')
      setCore(await api(`/应用/${appId}/停用核`))
      await loadOverview()
    } catch (e) { setErr(e.message) }
  }

  const fireProbe = async (mouth) => {
    setErr(''); setProbe('')
    const id = releaseId || (selected?.在途发版 || [])[0]?.编号
    if (!id) {
      setErr('请先选择或填写一个发版单编号作为写口探针')
      return
    }
    const path = mouth === '入闸'
      ? `/发版单/${id}/入闸`
      : mouth === '放行'
        ? `/发版单/${id}/放行`
        : `/发版单/${id}/晋升`
    const options = {
      method: 'POST',
      body: JSON.stringify(mouth === '晋升' ? { 目标环境: '预' } : {}),
    }
    try {
      const out = await api(path, options)
      setProbe(`写口泄漏：${mouth}探针未被拒绝，单子推进到 ${out.状态}`)
      setErr(`写口泄漏：${mouth} 仍然可推进；缺口必须钉住，停用灯不得为干净绿灯`)
    } catch (e) {
      setProbe(`${mouth}写口探针已被后端拒绝：${e.message}`)
    } finally {
      await loadCore(appId).catch(() => {})
      await loadOverview().catch(() => {})
    }
  }

  if (!overview) return <div className="panel">停用核加载中…</div>

  const lamp = selected?.灯 || overview.灯
  const gaps = selected?.缺口 || []
  const mouths = selected?.写口 || {}
  const releases = selected?.在途发版 || []
  const events = selected?.审计时序 || []

  return (
    <div className="panel disable-page" data-page="disable" data-testid="disable-page">
      <h2>停用页 · 停用标 / 写口拒 / 在途收口同核</h2>
      <p className="muted">
        成功不能只看回执绿灯：必须同时摸到停用标、入闸/晋升/放行写口拒绝、在途单收口痕迹和审计重放。
        若写口仍开，缺口灯会钉住泄漏，停用事务整笔退回。
      </p>

      <div className="row disable-toolbar">
        <label>应用
          <select data-testid="disable-app-select" value={appId} onChange={(e) => { setAppId(e.target.value); setCore(null) }}>
            {apps.map((a) => (
              <option key={a.应用编号} value={a.应用编号}>
                {a.应用} · {a.状态} · {a.灯文案 || a.灯}
              </option>
            ))}
          </select>
        </label>
        <DisableLamp light={overview.灯} text={`总览：${overview.灯文案}`} count={overview.缺口数} data-testid="overview-disable-lamp" />
        {selected && <DisableLamp light={lamp} text={selected.灯文案} count={selected.缺口数} data-testid="app-disable-lamp" />}
        <button type="button" className="danger disable-btn" data-testid="disable-submit" disabled={busy} onClick={runDisable}>
          {busy ? '停用同核中…' : '停用并同核收口'}
        </button>
        <button type="button" data-testid="disable-heal" onClick={heal}>重放收口</button>
        <button type="button" className="secondary" data-testid="disable-enable" onClick={enable}>恢复启用</button>
        <button type="button" className="secondary" data-testid="disable-refresh" onClick={() => loadOverview().catch((e) => setErr(e.message))}>刷新总核</button>
      </div>

      {err && <p className="err" role="alert" data-testid="disable-error">{err}</p>}
      {msg && <p className="ok" role="status" data-testid="disable-message">{msg}</p>}
      {probe && <p className="probe-result" role="status" data-testid="probe-result">{probe}</p>}

      {selected && (
        <>
          <div className="disable-same-screen" data-testid="same-screen-core">
            <section className="core-card">
              <h3>停用标与写口同屏对读</h3>
              <div className="row">
                <AppStatusBadge status={selected.状态} light={selected.灯} />
                <span data-field="停用标">{selected.停用标 ? '停用标=已落' : '停用标=未落/非同核'}</span>
                <span data-field="审计重放">审计重放={selected.审计重放 ? '可重放' : '缺事件'}</span>
              </div>
              <div className="mouth-grid">
                {['申请', '入闸', '流水线回执', '晋升', '放行', '回滚'].map((m) => {
                  const open = mouths[m]
                  return (
                    <div
                      key={m}
                      className={`mouth-item ${open ? 'mouth-open' : 'mouth-closed'}`}
                      data-mouth={m}
                      data-open={open ? '1' : '0'}
                    >
                      <b>{m}</b>
                      <span>{open ? '开放' : '已拒/灰态'}</span>
                    </div>
                  )
                })}
              </div>
              <div className="row probe-row">
                <label>探针发版单编号
                  <input data-testid="probe-release-input" value={releaseId} onChange={(e) => setReleaseId(e.target.value)} placeholder="发版单编号" />
                </label>
                <LockedButton mouth="入闸" closed={mouths.入闸 === false} data-probe="admit" data-testid="probe-admit" onClick={() => fireProbe('入闸')}>入闸写口探针</LockedButton>
                <LockedButton mouth="晋升" closed={mouths.晋升 === false} data-probe="promote" data-testid="probe-promote" onClick={() => fireProbe('晋升')}>晋升写口探针</LockedButton>
                <LockedButton mouth="放行" closed={mouths.放行 === false} data-probe="release" data-testid="probe-release" onClick={() => fireProbe('放行')}>放行写口探针</LockedButton>
              </div>
            </section>

            <section className="core-card">
              <h3>泄漏缺口</h3>
              {gaps.length === 0 ? (
                <p className="ok" data-testid="no-gaps">无缺口：停用标 ∪ 写口拒 ∪ 在途收口 ∪ 审计重放同核。</p>
              ) : (
                <ul className="gap-list" data-testid="gap-list">
                  {gaps.map((g, i) => (
                    <li key={`${g.code}-${i}`} data-disable-gap={g.code} data-gap-code={g.code}>
                      <b>{g.code}</b>：{g.缺口 || g.message}
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </div>

          <h3>在途发版旁读 / 发版单册同核</h3>
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th>编号</th><th>单号</th><th>状态</th><th>单态收口</th><th>在途收口</th><th>冻结/收口标</th><th>入闸口</th><th>晋升口</th><th>放行口</th></tr>
              </thead>
              <tbody>
                {releases.map((r) => (
                  <tr key={r.编号} data-release-id={r.编号} data-same-core={r.同核收口 ? '1' : '0'}>
                    <td>{r.编号}</td>
                    <td>{r.发版单号}</td>
                    <td>{r.状态}</td>
                    <td data-field="单态收口">{r.单态收口}</td>
                    <td>{r.在途收口 ? '已收口' : '未收'}</td>
                    <td><FrozenBadge row={r} /></td>
                    {['入闸', '晋升', '放行'].map((m) => (
                      <td key={m} data-release-mouth={m} data-open={r.写口?.[m] ? '1' : '0'}>
                        {r.写口?.[m] ? '可写' : '拒绝'}
                      </td>
                    ))}
                  </tr>
                ))}
                {releases.length === 0 && <tr><td colSpan={9} className="muted">无未收口发版单</td></tr>}
              </tbody>
            </table>
          </div>

          <h3>停用事件时序 / 审计重放</h3>
          <div className="table-wrap">
            <table>
              <thead><tr><th>时间</th><th>类别</th><th>关联</th><th>动作</th><th>备注</th></tr></thead>
              <tbody>
                {events.map((e) => (
                  <tr key={e.编号} data-audit-action={e.动作} data-audit-sequence={e.编号}>
                    <td>{e.时间}</td><td>{e.类别}</td><td>{e.关联编号 || '-'}</td><td>{e.动作}</td><td>{e.备注}</td>
                  </tr>
                ))}
                {events.length === 0 && <tr><td colSpan={5} className="muted">暂无停用/探针事件</td></tr>}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  )
}
