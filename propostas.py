#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
reunioes/propostas.py - Motor de Propostas de Ação Inteligentes para Bruno
Analisa o campo 'direcionado_para_bruno' do FLOW Reuniões, gera propostas
de mensagens concretas para grupos/contatos e publica no grupo WhatsApp MAESTRI
para aprovação com 1 clique/comando (@stark aprovar X).
"""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

HIDDEN = getattr(subprocess, 'CREATE_NO_WINDOW', 0)

PROMPTS_FILE_NAME = "propostas_pendentes.json"

def get_agy_bin():
    p1 = Path(r"~\AppData\Local\agy\bin\agy.exe")
    if p1.exists(): return p1
    p2 = Path(os.environ.get("LOCALAPPDATA", "")) / "agy" / "bin" / "agy.exe"
    if p2.exists(): return p2
    return "agy"

def gerar_propostas(root, mid):
    root = Path(root)
    job_file = root / "reunioes" / "jobs" / mid / "analysis.json"
    if not job_file.exists():
        return []

    data = json.loads(job_file.read_text(encoding="utf-8"))
    items = data.get("direcionado_para_bruno", [])
    if not items:
        # Tentar buscar em tasks onde owner contenha Bruno
        tasks = data.get("tasks", [])
        items = [
            {
                "area": "Geral",
                "action": t.get("description", ""),
                "details": t.get("description", ""),
                "quote": t.get("quote", ""),
                "timestamp": t.get("timestamp")
            }
            for t in tasks if t.get("owner") and "bruno" in str(t.get("owner")).lower()
        ]

    if not items:
        return []

    meeting_title = data.get("title") or mid

    # Prompt para o Gemini Flash estruturar mensagens prontas
    items_text = json.dumps(items, ensure_ascii=False, indent=2)
    prompt = f"""Você é o assistente executivo sênior de Bruno Yves (FLOW e SOPHA).
Com base nas tarefas que foram DIRECIONADAS A BRUNO na reunião "{meeting_title}", elabore para cada item uma proposta de ação EXECUTÁVEL:

REGRAS:
1. Se a tarefa envolver falar com cliente, parceiro, lojista ou pessoa (seja em grupo ou privado):
   - channel: "whatsapp_grupo" se for grupo (ex: Paycard, Lídia, Casa Pronta) ou "whatsapp_privado" se for para uma pessoa específica (ex: Matheus, Dávila, Tiago Basei).
   - destination: O nome exato provável do grupo ou contato no WhatsApp (ex: "Paycard", "Lídia", "Matheus").
   - draft_message: Redija a mensagem no PADRÃO OURO DE FORMATAÇÃO DO WHATSAPP (EXECUTIVE CLEAN):
     * NUNCA escreva blocos de texto contínuo sem quebras ("textão").
     * Saudação inicial em linha isolada (ex: "Olá, pessoal! Tudo bem?" ou "Boa tarde, pessoal!").
     * Pule SEMPRE uma linha em branco (\n\n) após a saudação.
     * Contexto curto e objetivo (máximo 1 a 2 linhas).
     * Se houver perguntas, tópicos ou requisitos, separe-os com quebras de linha usando marcadores limpos (• ou 1., 2.).
     * Destaque termos-chave, nomes de tabelas, sistemas e prazos com *negrito do WhatsApp* (ex: *tabela de produtos*, *API oficial*, *cartão na BM*).
     * Fechamento / Call-to-action sempre em parágrafo isolado após uma linha em branco (\n\n).
2. Se a tarefa for interna operacional (ex: documentar POP, participar de reunião, aplicar regra de 7 dias):
   - channel: "tarefa_interna" ou "youtrack"
   - destination: "Interno / Equipe"
   - draft_message: Resumo do passo a passo operacional para execução.

ITENS DIRECIONADOS A BRUNO:
{items_text}

Retorne ESTRITAMENTE um JSON válido (array de objetos, sem crases markdown) com os campos:
[
  {{
    "id": 1,
    "area": "Nome da Área ou Cliente",
    "action": "Ação resumida em 1 linha",
    "destination": "Nome do grupo ou contato",
    "channel": "whatsapp_grupo" | "whatsapp_privado" | "youtrack" | "tarefa_interna",
    "draft_message": "Texto completo da mensagem sugerida",
    "timestamp": "MM:SS"
  }}
]
"""
    agy_bin = get_agy_bin()
    propostas = []
    try:
        p = subprocess.run([
            str(agy_bin),
            "-p", prompt,
            "--model", "gemini-3.8-flash-low",
            "--disable-slash-commands",
            "--dangerously-skip-permissions"
        ], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=90, creationflags=HIDDEN)
        if p.returncode == 0 and p.stdout.strip():
            raw = p.stdout.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1]
                if raw.endswith("```"): raw = raw[:-3]
                raw = raw.strip()
            propostas = json.loads(raw)
    except Exception as err:
        print(f"[!] Erro ao gerar propostas com LLM: {err}", file=sys.stderr)

    # Fallback se LLM falhar
    if not propostas:
        for idx, it in enumerate(items, 1):
            ts = it.get("timestamp")
            ts_str = f"{int(ts // 60):02d}:{int(ts % 60):02d}" if ts else "00:00"
            area = it.get("area", "Geral")
            action = it.get("action", "")
            propostas.append({
                "id": idx,
                "area": area,
                "action": action,
                "destination": area,
                "channel": "whatsapp_grupo" if any(w in area.lower() for w in ("paycard", "lídia", "lidia", "mariage", "casa pronta", "oca")) else "tarefa_interna",
                "draft_message": f"Olá equipe {area}! {action}.",
                "timestamp": ts_str
            })

    # Adicionar metadados
    from operacoes.formatacao_whatsapp import organizar_mensagem_whatsapp
    for p_item in propostas:
        if p_item.get("draft_message"):
            p_item["draft_message"] = organizar_mensagem_whatsapp(p_item["draft_message"])
        p_item["meeting_id"] = mid
        p_item["meeting_title"] = meeting_title
        p_item["status"] = "aguardando_aprovacao"
        p_item["created_at"] = time.time()

    # Salvar no job folder
    job_prop_file = root / "reunioes" / "jobs" / mid / "propostas.json"
    job_prop_file.write_text(json.dumps(propostas, ensure_ascii=False, indent=2), encoding="utf-8")

    # Atualizar repositório global de propostas pendentes em operacoes/
    global_file = root / "operacoes" / PROMPTS_FILE_NAME
    global_propostas = []
    if global_file.exists():
        try:
            global_propostas = json.loads(global_file.read_text(encoding="utf-8"))
        except Exception:
            pass
    
    # Remover antigas deste meeting e adicionar novas
    global_propostas = [gp for gp in global_propostas if gp.get("meeting_id") != mid]
    global_propostas.extend(propostas)
    global_file.write_text(json.dumps(global_propostas, ensure_ascii=False, indent=2), encoding="utf-8")

    return propostas

def formatar_mensagem_whatsapp(propostas, meeting_title):
    if not propostas:
        return "", ""

    # Mensagem 1 (Título / Alerta de 1 Linha)
    msg1 = f"🎯 FLOW Reuniões: {len(propostas)} ações identificadas para Bruno na reunião [{meeting_title[:40]}]"

    # Mensagem 2 (Plano de Ação Estruturado)
    linhas = [
        "📋 PLANO DE AÇÃO PROPOSTO (Aguardando Aprovação de Bruno):",
        ""
    ]

    whatsapp_propostas = [p for p in propostas if p.get("channel") in ("whatsapp_grupo", "whatsapp_privado")]
    internas = [p for p in propostas if p.get("channel") not in ("whatsapp_grupo", "whatsapp_privado")]

    if whatsapp_propostas:
        linhas.append("💬 MENSAGENS SUGERIDAS PARA ENVIO NO WHATSAPP:")
        for p in whatsapp_propostas:
            pid = p["id"]
            area = p.get("area", "")
            action = p.get("action", "")
            dest = p.get("destination", "")
            msg = p.get("draft_message", "")
            ts = p.get("timestamp", "")
            linhas.append(f"[{pid}] {area} — {action} ({ts})")
            linhas.append(f"📍 Destino: {dest}")
            linhas.append(f"✍️ Texto sugerido: \"{msg}\"")
            linhas.append(f"👉 Aprovar: @stark aprovar {pid}")
            linhas.append("")

    if internas:
        linhas.append("📌 AÇÕES OPERACIONAIS / INTERNAS:")
        for p in internas:
            pid = p["id"]
            action = p.get("action", "")
            linhas.append(f"[{pid}] {action}")
            linhas.append(f"👉 Concluir/Registrar: @stark concluir {pid}")
            linhas.append("")

    linhas.append("⚡ Para aprovar todos os envios de uma vez, responda:")
    linhas.append("@stark aprovar tudo")

    msg2 = "\n".join(linhas)
    return msg1, msg2

def publicar_no_grupo_maestri(root, msg1, msg2):
    root = Path(root)
    reg = json.loads((root / "registry.json").read_text(encoding="utf-8-sig"))
    stark_tid = reg["roles"]["orquestrador"]["terminalId"]
    reg["primary_terminal"] = stark_tid
    import operacoes.whatsapp as op_wa
    from operacoes.whatsapp import Client
    from operacoes.audio_whatsapp import open_for_read

    portal_name = "WhatsApp — Atendimento FLOW #2"
    op_wa.PORTAL = portal_name
    client = Client({"runtime": str(root), "registry": reg, "whatsapp_portal": portal_name, "primary_terminal": stark_tid})

    # Abrir grupo MAESTRI e postar as 2 mensagens
    client = open_for_read(client.context, "MAESTRI")
    
    # Enviar mensagem 1
    client.set_draft(msg1)
    time.sleep(0.4)
    client.commit()
    time.sleep(1.0)

    # Enviar mensagem 2
    client.set_draft(msg2)
    time.sleep(0.5)
    client.commit()
    return True

def gerar_e_publicar_propostas(root, mid):
    root = Path(root)
    # Evitar notificar a mesma reunião duas vezes
    lock_file = root / "reunioes" / "jobs" / mid / "notified_maestri.lock"
    if lock_file.exists():
        print(f"[*] Reunião {mid} já foi notificada anteriormente.")
        return False

    propostas = gerar_propostas(root, mid)
    if not propostas:
        return False

    job_file = root / "reunioes" / "jobs" / mid / "analysis.json"
    data = json.loads(job_file.read_text(encoding="utf-8")) if job_file.exists() else {}
    title = data.get("title") or mid

    msg1, msg2 = formatar_mensagem_whatsapp(propostas, title)
    try:
        publicar_no_grupo_maestri(root, msg1, msg2)
        lock_file.write_text(json.dumps({"notified_at": time.time(), "items_count": len(propostas)}), encoding="utf-8")
        print(f"[+] Propostas da reunião {mid} publicadas com sucesso no grupo MAESTRI!")
        return True
    except Exception as err:
        print(f"[!] Erro ao publicar propostas no WhatsApp: {err}", file=sys.stderr)
        return False

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Uso: python propostas.py <root> <meeting_id> [--publish]")
        sys.exit(1)
    root_p = sys.argv[1]
    m_id = sys.argv[2]
    should_publish = "--publish" in sys.argv

    props = gerar_propostas(root_p, m_id)
    print(f"Geradas {len(props)} propostas.")
    if should_publish:
        m1, m2 = formatar_mensagem_whatsapp(props, m_id)
        print("\n--- MENSAGEM 1 ---")
        print(m1)
        print("\n--- MENSAGEM 2 ---")
        print(m2)
