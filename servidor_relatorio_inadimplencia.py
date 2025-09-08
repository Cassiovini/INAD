import pandas as pd
import os
import logging
import json
from datetime import datetime, timedelta
from flask import Flask, render_template_string, request, jsonify, redirect, url_for, send_file
import threading
import webbrowser

# Configuração de logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Arquivo para salvar observações
OBSERVACOES_FILE = "observacoes_inadimplencia.json"

# Configuração de upload
UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'xlsx', 'xls'}

# Criar pasta de upload se não existir
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

def formatar_valor(valor, tipo='moeda'):
    """Formata valores para exibição"""
    if pd.isna(valor) or valor is None:
        return "R$ 0,00"
    
    try:
        if tipo == 'moeda':
            return f"R$ {valor:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
        elif tipo == 'percentual':
            return f"{valor:.2f}%"
        else:
            return f"{valor:,.0f}"
    except:
        return "R$ 0,00"

def get_color_atingimento(percentual):
    """Retorna cor baseada no percentual de inadimplência"""
    try:
        if pd.isna(percentual) or percentual is None:
            return "#666666"  # Cinza para valores nulos
        
        percentual = float(percentual)
        
        if percentual <= 5:
            return "#00FF00"  # Verde para até 5%
        elif percentual <= 10:
            return "#90EE90"  # Verde claro para 5-10%
        elif percentual <= 15:
            return "#FFFF00"  # Amarelo para 10-15%
        elif percentual <= 20:
            return "#FFA500"  # Laranja para 15-20%
        else:
            return "#FF0000"  # Vermelho para mais de 20%
    except:
        return "#666666"  # Cinza para erros

def allowed_file(filename):
    """Verifica se a extensão do arquivo é permitida"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def obter_dados_inadimplencia():
    """Obtém dados de inadimplência do período especificado"""
    try:
        # Calcular período dinâmico: mês atual, dia atual menos 1
        hoje = datetime.now()
        dia_atual_menos_1 = hoje - timedelta(days=1)
        
        # Data início: primeiro dia do mês atual
        data_inicio = hoje.replace(day=1)
        # Data fim: dia atual menos 1
        data_fim = dia_atual_menos_1
        
        logger.info(f"📅 Buscando dados de inadimplência de {data_inicio.strftime('%d/%m/%Y')} até {data_fim.strftime('%d/%m/%Y')}")
        
        # Verificar se o arquivo existe (primeiro na pasta uploads, depois no diretório raiz)
        arquivo_excel = None
        
        # Procurar na pasta uploads
        for filename in os.listdir(UPLOAD_FOLDER):
            if allowed_file(filename) and 'RESUMO_VENDAS' in filename.upper():
                arquivo_excel = os.path.join(UPLOAD_FOLDER, filename)
                break
        
        # Se não encontrou na pasta uploads, procurar no diretório raiz
        if not arquivo_excel:
            if os.path.exists("RESUMO_VENDAS.xlsx"):
                arquivo_excel = "RESUMO_VENDAS.xlsx"
            else:
                logger.error(f"❌ Arquivo RESUMO_VENDAS.xlsx não encontrado")
                logger.info("💡 Faça upload do arquivo Excel na página inicial")
                return None
        
        # Carregar dados da aba BASE_INADI
        df_inadimplencia = pd.read_excel(arquivo_excel, sheet_name='BASE_INADI')
        
        if df_inadimplencia.empty:
            logger.warning("⚠️ Aba BASE_INADI está vazia")
            return None
        
        # Verificar colunas disponíveis
        colunas_disponiveis = df_inadimplencia.columns.tolist()
        logger.info(f"📋 Colunas disponíveis: {colunas_disponiveis}")
        
        # Mapear colunas conforme estrutura do arquivo
        if 'RCA' in df_inadimplencia.columns:
            df_inadimplencia = df_inadimplencia.rename(columns={
                'RCA': 'COD_VENDEDOR',
                'VALOR': 'VALOR_TITULO',
                'DIAS': 'DIAS_ATRASO',
                'CLIENTE': 'NOME_CLIENTE',
                'VENC': 'DATA_VENCIMENTO',
                'DUPLIC': 'COD_CLIENTE'
            })
        
        # Adicionar colunas que podem não existir
        if 'NOME_VENDEDOR' not in df_inadimplencia.columns:
            if 'NOME_RCA' in df_inadimplencia.columns:
                df_inadimplencia['NOME_VENDEDOR'] = df_inadimplencia['NOME_RCA']
            else:
                df_inadimplencia['NOME_VENDEDOR'] = 'Vendedor ' + df_inadimplencia['COD_VENDEDOR'].astype(str)
        
        if 'COD_CLIENTE' not in df_inadimplencia.columns:
            df_inadimplencia['COD_CLIENTE'] = 'Cliente'
        
        if 'NOME_CLIENTE' not in df_inadimplencia.columns:
            df_inadimplencia['NOME_CLIENTE'] = 'Cliente'
        
        if 'DATA_VENCIMENTO' not in df_inadimplencia.columns:
            # Calcular data de vencimento baseada nos dias de atraso
            df_inadimplencia['DATA_VENCIMENTO'] = (hoje - pd.to_timedelta(df_inadimplencia['DIAS_ATRASO'], unit='D')).dt.strftime('%Y-%m-%d')
        
        if 'STATUS_TITULO' not in df_inadimplencia.columns:
            df_inadimplencia['STATUS_TITULO'] = 'EM ABERTO'
        
        if 'VALOR_PAGO' not in df_inadimplencia.columns:
            df_inadimplencia['VALOR_PAGO'] = 0
        
        if 'DATA_PAGAMENTO' not in df_inadimplencia.columns:
            df_inadimplencia['DATA_PAGAMENTO'] = None
        
        if 'OBSERVACOES' not in df_inadimplencia.columns:
            df_inadimplencia['OBSERVACOES'] = ''
        
        # MOSTRAR INADIMPLÊNCIA GERAL (INCLUINDO VENDEDORES QUE SAÍRAM)
        logger.info(f"📊 Total de registros de inadimplência: {len(df_inadimplencia)}")
        logger.info(f"✅ Dados de inadimplência carregados (incluindo vendedores que saíram)")
        
        return df_inadimplencia
        
    except Exception as e:
        logger.error(f"❌ Erro ao obter dados de inadimplência: {e}")
        return None

def calcular_metricas_inadimplencia(df_inadimplencia):
    """Calcula métricas de inadimplência"""
    try:
        # Agrupar por vendedor
        df_por_vendedor = df_inadimplencia.groupby(['COD_VENDEDOR', 'NOME_VENDEDOR']).agg({
            'VALOR_TITULO': ['sum', 'count'],
            'VALOR_PAGO': 'sum',
            'DIAS_ATRASO': 'mean'
        }).round(2)
        
        # Flatten das colunas
        df_por_vendedor.columns = ['VALOR_TOTAL_INADIMPLENCIA', 'QTD_TITULOS', 'VALOR_PAGO', 'DIAS_ATRASO_MEDIO']
        df_por_vendedor = df_por_vendedor.reset_index()
        
        # Calcular valor em aberto
        df_por_vendedor['VALOR_EM_ABERTO'] = df_por_vendedor['VALOR_TOTAL_INADIMPLENCIA'] - df_por_vendedor['VALOR_PAGO']
        
        # Calcular percentual de inadimplência
        df_por_vendedor['%_INADIMPLENCIA'] = (df_por_vendedor['VALOR_EM_ABERTO'] / df_por_vendedor['VALOR_TOTAL_INADIMPLENCIA'] * 100).round(2)
        
        # ORDENAR DO MENOR PARA O MAIOR DIAS MÉDIO ATRASO
        df_por_vendedor = df_por_vendedor.sort_values('DIAS_ATRASO_MEDIO', ascending=True)
        
        logger.info(f"📊 Vendedores ordenados por Dias Médio Atraso (menor para maior)")
        
        return df_por_vendedor
        
    except Exception as e:
        logger.error(f"❌ Erro ao calcular métricas: {e}")
        return None

def carregar_observacoes():
    """Carrega observações salvas"""
    try:
        if os.path.exists(OBSERVACOES_FILE):
            with open(OBSERVACOES_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        return []
    except Exception as e:
        logger.error(f"❌ Erro ao carregar observações: {e}")
        return []

def salvar_observacao(observacao):
    """Salva uma nova observação"""
    try:
        observacoes = carregar_observacoes()
        observacao['id'] = len(observacoes) + 1
        observacao['data_envio'] = datetime.now().isoformat()
        observacoes.append(observacao)
        
        with open(OBSERVACOES_FILE, 'w', encoding='utf-8') as f:
            json.dump(observacoes, f, ensure_ascii=False, indent=2)
        
        logger.info(f"✅ Observação salva: {observacao['nome_vendedor']}")
        return True
    except Exception as e:
        logger.error(f"❌ Erro ao salvar observação: {e}")
        return False

def gerar_pagina_upload():
    """Gera página de upload quando não há dados"""
    html_content = """
    <!DOCTYPE html>
    <html lang="pt-BR">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Upload de Dados - Relatório de Inadimplência</title>
        <style>
            body {
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                margin: 0;
                padding: 20px;
                background-color: #f5f5f5;
                color: #333;
            }
            .container {
                max-width: 600px;
                margin: 0 auto;
                background-color: white;
                border-radius: 10px;
                box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
                overflow: hidden;
            }
            .header {
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
                padding: 30px;
                text-align: center;
            }
            .header h1 {
                margin: 0;
                font-size: 2.5em;
                font-weight: 300;
            }
            .header p {
                margin: 10px 0 0 0;
                font-size: 1.1em;
                opacity: 0.9;
            }
            .upload-section {
                padding: 40px;
                text-align: center;
            }
            .upload-info {
                background-color: #e3f2fd;
                border: 1px solid #2196f3;
                border-radius: 6px;
                padding: 20px;
                margin-bottom: 30px;
                color: #1976d2;
            }
            .upload-form {
                margin-bottom: 30px;
            }
            .file-input {
                display: none;
            }
            .file-label {
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
                padding: 15px 30px;
                border-radius: 6px;
                cursor: pointer;
                display: inline-block;
                font-weight: 600;
                transition: all 0.3s ease;
            }
            .file-label:hover {
                transform: translateY(-2px);
                box-shadow: 0 4px 8px rgba(0, 0, 0, 0.2);
            }
            .btn-upload {
                background: #28a745;
                color: white;
                border: none;
                padding: 15px 30px;
                border-radius: 6px;
                font-size: 16px;
                font-weight: 600;
                cursor: pointer;
                margin-top: 20px;
                transition: all 0.3s ease;
            }
            .btn-upload:hover {
                background: #218838;
            }
            .btn-download {
                background: #17a2b8;
                color: white;
                border: none;
                padding: 12px 25px;
                border-radius: 6px;
                font-size: 14px;
                font-weight: 600;
                cursor: pointer;
                text-decoration: none;
                display: inline-block;
                margin-top: 20px;
                transition: all 0.3s ease;
            }
            .btn-download:hover {
                background: #138496;
            }
            .status {
                margin-top: 20px;
                padding: 15px;
                border-radius: 6px;
                display: none;
            }
            .status.success {
                background-color: #d4edda;
                color: #155724;
                border: 1px solid #c3e6cb;
            }
            .status.error {
                background-color: #f8d7da;
                color: #721c24;
                border: 1px solid #f5c6cb;
            }
            .footer {
                background-color: #495057;
                color: white;
                text-align: center;
                padding: 20px;
                font-size: 0.9em;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>📊 Relatório de Inadimplência</h1>
                <p>Upload de dados para análise</p>
            </div>
            
            <div class="upload-section">
                <div class="upload-info">
                    <strong>💡 Como usar:</strong><br>
                    1. Faça download do template Excel<br>
                    2. Preencha com seus dados na aba "BASE_INADI"<br>
                    3. Faça upload do arquivo preenchido<br>
                    4. Acesse o relatório de inadimplência
                </div>
                
                <div class="upload-form">
                    <form id="uploadForm" enctype="multipart/form-data">
                        <input type="file" id="arquivo" name="arquivo" class="file-input" accept=".xlsx,.xls" required>
                        <label for="arquivo" class="file-label">📁 Selecionar Arquivo Excel</label>
                        <br>
                        <button type="submit" class="btn-upload">📤 Enviar Arquivo</button>
                    </form>
                </div>
                
                <a href="/download" class="btn-download">📥 Download Template Excel</a>
                
                <div id="status" class="status"></div>
            </div>
            
            <div class="footer">
                <p>Sistema de Gestão de Inadimplência</p>
            </div>
        </div>
        
        <script>
        document.getElementById('uploadForm').addEventListener('submit', function(e) {
            e.preventDefault();
            
            const formData = new FormData();
            const fileInput = document.getElementById('arquivo');
            const statusDiv = document.getElementById('status');
            
            if (fileInput.files.length === 0) {
                showStatus('Por favor, selecione um arquivo.', 'error');
                return;
            }
            
            formData.append('arquivo', fileInput.files[0]);
            
            fetch('/upload', {
                method: 'POST',
                body: formData
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    showStatus(data.message, 'success');
                    setTimeout(() => {
                        window.location.reload();
                    }, 2000);
                } else {
                    showStatus('Erro: ' + data.error, 'error');
                }
            })
            .catch(error => {
                showStatus('Erro ao enviar arquivo: ' + error, 'error');
            });
        });
        
        function showStatus(message, type) {
            const statusDiv = document.getElementById('status');
            statusDiv.textContent = message;
            statusDiv.className = 'status ' + type;
            statusDiv.style.display = 'block';
        }
        </script>
    </body>
    </html>
    """
    return html_content

def gerar_html_relatorio(df_inadimplencia, df_metricas, observacoes):
    """Gera HTML do relatório"""
    try:
        hoje = datetime.now()
        dia_atual_menos_1 = hoje - timedelta(days=1)
        data_inicio = hoje.replace(day=1)
        data_fim = dia_atual_menos_1
        
        # Calcular totais
        total_valor_inadimplencia = df_inadimplencia['VALOR_TITULO'].sum()
        total_titulos = len(df_inadimplencia)
        total_valor_pago = df_inadimplencia['VALOR_PAGO'].sum()
        total_em_aberto = total_valor_inadimplencia - total_valor_pago
        
        # Gerar opções de vendedores para o filtro
        vendedores_unicos = df_inadimplencia[['COD_VENDEDOR', 'NOME_VENDEDOR']].drop_duplicates()
        opcoes_vendedores = ""
        for _, row in vendedores_unicos.iterrows():
            opcoes_vendedores += f'<option value="{row["COD_VENDEDOR"]}">{row["COD_VENDEDOR"]} - {row["NOME_VENDEDOR"]}</option>'
        
        # Gerar HTML
        html_content = f"""
        <!DOCTYPE html>
        <html lang="pt-BR">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Relatório de Inadimplência - {hoje.strftime('%d/%m/%Y')}</title>
            <style>
                body {{
                    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                    margin: 0;
                    padding: 20px;
                    background-color: #f5f5f5;
                    color: #333;
                }}
                .container {{
                    max-width: 1200px;
                    margin: 0 auto;
                    background-color: white;
                    border-radius: 10px;
                    box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
                    overflow: hidden;
                }}
                .header {{
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    color: white;
                    padding: 30px;
                    text-align: center;
                }}
                .header h1 {{
                    margin: 0;
                    font-size: 2.5em;
                    font-weight: 300;
                }}
                .header p {{
                    margin: 10px 0 0 0;
                    font-size: 1.1em;
                    opacity: 0.9;
                }}
                .upload-inline {{
                    display: flex;
                    gap: 10px;
                    justify-content: center;
                    align-items: center;
                    margin-top: 10px;
                }}
                .upload-inline input[type="file"] {{
                    display: none;
                }}
                .upload-inline .file-label {{
                    background: #17a2b8;
                    color: white;
                    padding: 8px 14px;
                    border-radius: 6px;
                    cursor: pointer;
                    font-weight: 600;
                }}
                .upload-inline .btn-upload {{
                    background: #28a745;
                    color: white;
                    border: none;
                    padding: 8px 14px;
                    border-radius: 6px;
                    font-weight: 600;
                    cursor: pointer;
                }}
                .periodo {{
                    background-color: #f8f9fa;
                    padding: 15px;
                    text-align: center;
                    border-bottom: 1px solid #e9ecef;
                }}
                .periodo strong {{
                    color: #495057;
                }}
                .resumo {{
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
                    gap: 20px;
                    padding: 30px;
                    background-color: #f8f9fa;
                }}
                .card {{
                    background: white;
                    padding: 25px;
                    border-radius: 8px;
                    box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
                    text-align: center;
                }}
                .card h3 {{
                    margin: 0 0 15px 0;
                    color: #495057;
                    font-size: 1.1em;
                }}
                .card .valor {{
                    font-size: 2em;
                    font-weight: bold;
                    color: #dc3545;
                }}
                .card .label {{
                    font-size: 0.9em;
                    color: #6c757d;
                    margin-top: 5px;
                }}
                .tabela-container {{
                    padding: 30px;
                }}
                .tabela-container h2 {{
                    color: #495057;
                    margin-bottom: 20px;
                    font-size: 1.5em;
                }}
                table {{
                    width: 100%;
                    border-collapse: collapse;
                    margin-bottom: 30px;
                    background: white;
                    border-radius: 8px;
                    overflow: hidden;
                    box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
                }}
                th {{
                    background-color: #495057;
                    color: white;
                    padding: 15px;
                    text-align: left;
                    font-weight: 600;
                }}
                td {{
                    padding: 12px 15px;
                    border-bottom: 1px solid #e9ecef;
                }}
                tr:hover {{
                    background-color: #f8f9fa;
                }}
                .status-bom {{
                    color: #28a745;
                    font-weight: bold;
                }}
                .status-medio {{
                    color: #ffc107;
                    font-weight: bold;
                }}
                .status-ruim {{
                    color: #dc3545;
                    font-weight: bold;
                }}
                .footer {{
                    background-color: #495057;
                    color: white;
                    text-align: center;
                    padding: 20px;
                    font-size: 0.9em;
                }}
                .observacoes-section {{
                    padding: 30px;
                    background-color: #f8f9fa;
                    border-top: 1px solid #e9ecef;
                }}
                .observacoes-section h3 {{
                    color: #495057;
                    margin-bottom: 20px;
                    font-size: 1.5em;
                    text-align: center;
                }}
                .form-observacao {{
                    max-width: 600px;
                    margin: 0 auto;
                    background: white;
                    padding: 25px;
                    border-radius: 8px;
                    box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
                }}
                .form-group {{
                    margin-bottom: 20px;
                }}
                .form-group label {{
                    display: block;
                    margin-bottom: 8px;
                    color: #495057;
                    font-weight: 600;
                }}
                .form-group input, .form-group textarea {{
                    width: 100%;
                    padding: 12px;
                    border: 1px solid #ced4da;
                    border-radius: 4px;
                    font-size: 14px;
                    font-family: inherit;
                }}
                .form-group textarea {{
                    min-height: 120px;
                    resize: vertical;
                }}
                .btn-enviar {{
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    color: white;
                    border: none;
                    padding: 12px 30px;
                    border-radius: 6px;
                    font-size: 16px;
                    font-weight: 600;
                    cursor: pointer;
                    transition: all 0.3s ease;
                }}
                .btn-enviar:hover {{
                    transform: translateY(-2px);
                    box-shadow: 0 4px 8px rgba(0, 0, 0, 0.2);
                }}
                .info-observacao {{
                    background-color: #e3f2fd;
                    border: 1px solid #2196f3;
                    border-radius: 6px;
                    padding: 15px;
                    margin-bottom: 20px;
                    color: #1976d2;
                }}
                .observacoes-lista {{
                    margin-top: 30px;
                    background: white;
                    padding: 25px;
                    border-radius: 8px;
                    box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
                }}
                .observacao-item {{
                    border-bottom: 1px solid #e9ecef;
                    padding: 15px 0;
                }}
                .observacao-item:last-child {{
                    border-bottom: none;
                }}
                .observacao-header {{
                    display: flex;
                    justify-content: space-between;
                    margin-bottom: 10px;
                }}
                .observacao-vendedor {{
                    font-weight: bold;
                    color: #495057;
                }}
                .observacao-data {{
                    color: #6c757d;
                    font-size: 0.9em;
                }}
                .observacao-texto {{
                    color: #333;
                    line-height: 1.5;
                }}
                .btn-atualizar {{
                    background: #28a745;
                    color: white;
                    border: none;
                    padding: 10px 20px;
                    border-radius: 4px;
                    cursor: pointer;
                    margin-bottom: 20px;
                }}
                .filtros-section {{
                    padding: 20px;
                    background-color: #f8f9fa;
                    border-bottom: 1px solid #e9ecef;
                }}
                .filtros-container {{
                    display: flex;
                    gap: 15px;
                    flex-wrap: wrap;
                    align-items: center;
                    justify-content: center;
                }}
                .filtro-item {{
                    display: flex;
                    flex-direction: column;
                    align-items: center;
                }}
                .filtro-item label {{
                    font-weight: 600;
                    color: #495057;
                    margin-bottom: 5px;
                    font-size: 0.9em;
                }}
                .filtro-item select, .filtro-item input {{
                    padding: 8px 12px;
                    border: 1px solid #ced4da;
                    border-radius: 4px;
                    font-size: 14px;
                    min-width: 150px;
                }}
                .btn-filtrar {{
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    color: white;
                    border: none;
                    padding: 8px 20px;
                    border-radius: 4px;
                    cursor: pointer;
                    font-weight: 600;
                    transition: all 0.3s ease;
                }}
                .btn-filtrar:hover {{
                    transform: translateY(-1px);
                    box-shadow: 0 2px 4px rgba(0, 0, 0, 0.2);
                }}
                .btn-limpar {{
                    background: #6c757d;
                    color: white;
                    border: none;
                    padding: 8px 20px;
                    border-radius: 4px;
                    cursor: pointer;
                    font-weight: 600;
                    transition: all 0.3s ease;
                }}
                .btn-limpar:hover {{
                    background: #5a6268;
                }}
                .filtro-ativo {{
                    background-color: #e3f2fd;
                    border: 2px solid #2196f3;
                    padding: 15px;
                    border-radius: 8px;
                    margin-bottom: 20px;
                    text-align: center;
                }}
                .filtro-ativo strong {{
                    color: #1976d2;
                }}
                @media (max-width: 768px) {{
                    .resumo {{
                        grid-template-columns: 1fr;
                    }}
                    table {{
                        font-size: 0.9em;
                    }}
                    th, td {{
                        padding: 8px;
                    }}
                    .form-observacao {{
                        margin: 0 15px;
                    }}
                    .filtros-container {{
                        flex-direction: column;
                        gap: 10px;
                    }}
                    .filtro-item select, .filtro-item input {{
                        min-width: 200px;
                    }}
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>📊 Relatório de Inadimplência</h1>
                    <p>Análise detalhada de títulos em atraso</p>
                    <div class="upload-inline">
                        <form id="uploadFormInline" enctype="multipart/form-data">
                            <input type="file" id="arquivoInline" name="arquivo" accept=".xlsx,.xls" required>
                            <label for="arquivoInline" class="file-label">📁 Selecionar Excel</label>
                            <button type="submit" class="btn-upload">📤 Enviar</button>
                        </form>
                    </div>
                </div>
                
                <div class="periodo">
                    <strong>Período de Análise:</strong> {data_inicio.strftime('%d/%m/%Y')} até {data_fim.strftime('%d/%m/%Y')}
                </div>
                
                <div class="filtros-section">
                    <h3 style="text-align: center; margin-bottom: 20px; color: #495057;">🔍 Filtros de Visualização</h3>
                    <div class="filtros-container">
                        <div class="filtro-item">
                            <label for="filtro-vendedor">Vendedor:</label>
                            <select id="filtro-vendedor">
                                <option value="">Todos os Vendedores</option>
                                {opcoes_vendedores}
                            </select>
                        </div>
                        <div class="filtro-item">
                            <label for="filtro-status">Status:</label>
                            <select id="filtro-status">
                                <option value="">Todos os Status</option>
                                <option value="BOM">BOM</option>
                                <option value="MÉDIO">MÉDIO</option>
                                <option value="RUIM">RUIM</option>
                            </select>
                        </div>
                        <div class="filtro-item">
                            <label for="filtro-dias">Dias Atraso:</label>
                            <select id="filtro-dias">
                                <option value="">Todos</option>
                                <option value="0-10">0-10 dias</option>
                                <option value="11-30">11-30 dias</option>
                                <option value="31-60">31-60 dias</option>
                                <option value="60+">60+ dias</option>
                            </select>
                        </div>
                        <div class="filtro-item">
                            <label for="filtro-valor">Valor Mínimo:</label>
                            <input type="number" id="filtro-valor" placeholder="R$ 0,00" min="0" step="0.01">
                        </div>
                        <div class="filtro-item">
                            <button class="btn-filtrar" onclick="aplicarFiltros()">🔍 Filtrar</button>
                        </div>
                        <div class="filtro-item">
                            <button class="btn-limpar" onclick="limparFiltros()">🗑️ Limpar</button>
                        </div>
                    </div>
                    <div id="filtro-ativo-info" style="display: none;"></div>
                </div>
                
                <div class="resumo">
                    <div class="card">
                        <h3>💰 Valor Total</h3>
                        <div class="valor">{formatar_valor(total_valor_inadimplencia)}</div>
                        <div class="label">Títulos em Inadimplência</div>
                    </div>
                    <div class="card">
                        <h3>📄 Quantidade</h3>
                        <div class="valor">{total_titulos:,}</div>
                        <div class="label">Títulos</div>
                    </div>
                    <div class="card">
                        <h3>💳 Valor Pago</h3>
                        <div class="valor">{formatar_valor(total_valor_pago)}</div>
                        <div class="label">Total Pago</div>
                    </div>
                    <div class="card">
                        <h3>⚠️ Em Aberto</h3>
                        <div class="valor">{formatar_valor(total_em_aberto)}</div>
                        <div class="label">Valor Pendente</div>
                    </div>
                </div>
                
                <div class="tabela-container">
                    <h2>📋 Resumo por Vendedor</h2>
                    <table id="tabela-resumo">
                        <thead>
                            <tr>
                                <th>Código</th>
                                <th>Vendedor</th>
                                <th>Valor Total</th>
                                <th>Qtd Títulos</th>
                                <th>Valor Pago</th>
                                <th>Em Aberto</th>
                                <th>% Inadimplência</th>
                                <th>Dias Médio Atraso</th>
                                <th>Status</th>
                            </tr>
                        </thead>
                        <tbody>
        """
        
        # Adicionar linhas da tabela
        for _, row in df_metricas.iterrows():
            # Determinar status baseado no percentual
            percentual = row['%_INADIMPLENCIA']
            if percentual <= 10:
                status_class = "status-bom"
                status_text = "BOM"
            elif percentual <= 20:
                status_class = "status-medio"
                status_text = "MÉDIO"
            else:
                status_class = "status-ruim"
                status_text = "RUIM"
            
            html_content += f"""
                            <tr>
                                <td>{row['COD_VENDEDOR']}</td>
                                <td>{row['NOME_VENDEDOR']}</td>
                                <td>{formatar_valor(row['VALOR_TOTAL_INADIMPLENCIA'])}</td>
                                <td>{row['QTD_TITULOS']:,}</td>
                                <td>{formatar_valor(row['VALOR_PAGO'])}</td>
                                <td>{formatar_valor(row['VALOR_EM_ABERTO'])}</td>
                                <td>{row['%_INADIMPLENCIA']:.1f}%</td>
                                <td>{row['DIAS_ATRASO_MEDIO']:.0f} dias</td>
                                <td class="{status_class}">{status_text}</td>
                            </tr>
            """
        
        html_content += """
                        </tbody>
                    </table>
                    
                    <h2>📋 Detalhamento por Cliente</h2>
                    <table id="tabela-detalhamento">
                        <thead>
                            <tr>
                                <th>Código Cliente</th>
                                <th>Nome Cliente</th>
                                <th>Vendedor</th>
                                <th>Valor Título</th>
                                <th>Data Vencimento</th>
                                <th>Dias Atraso</th>
                                <th>Status</th>
                                <th>Valor Pago</th>
                                <th>Data Pagamento</th>
                            </tr>
                        </thead>
                        <tbody>
        """
        
        # Adicionar detalhamento por cliente (ordenado por dias de atraso)
        df_inadimplencia_ordenado = df_inadimplencia.sort_values('DIAS_ATRASO', ascending=True)
        
        for _, row in df_inadimplencia_ordenado.iterrows():
            # Determinar status do título
            if pd.isna(row['VALOR_PAGO']) or row['VALOR_PAGO'] == 0:
                status_titulo = "EM ABERTO"
                status_class = "status-ruim"
            else:
                status_titulo = "PAGO PARCIAL"
                status_class = "status-medio"
            
            html_content += f"""
                            <tr>
                                <td>{row['COD_CLIENTE']}</td>
                                <td>{row['NOME_CLIENTE']}</td>
                                <td>{row['NOME_VENDEDOR']}</td>
                                <td>{formatar_valor(row['VALOR_TITULO'])}</td>
                                <td>{row['DATA_VENCIMENTO']}</td>
                                <td>{row['DIAS_ATRASO']} dias</td>
                                <td class="{status_class}">{status_titulo}</td>
                                <td>{formatar_valor(row['VALOR_PAGO'])}</td>
                                <td>{row['DATA_PAGAMENTO'] if pd.notna(row['DATA_PAGAMENTO']) else '-'}</td>
                            </tr>
            """
        
        html_content += f"""
                        </tbody>
                    </table>
                </div>
                
                <div class="observacoes-section">
                    <h3>📝 Adicionar Observação</h3>
                    <div class="form-observacao">
                        <div class="info-observacao">
                            <strong>💡 Como usar:</strong> Preencha os campos abaixo para adicionar observações sobre sua inadimplência. 
                            Suas observações serão enviadas para a gestão e podem ajudar no acompanhamento dos casos.
                        </div>
                        
                        <form id="formObservacao" onsubmit="enviarObservacao(event)">
                            <div class="form-group">
                                <label for="nome_vendedor">Nome do Vendedor:</label>
                                <input type="text" id="nome_vendedor" name="nome_vendedor" placeholder="Digite seu nome completo" required>
                            </div>
                            
                            <div class="form-group">
                                <label for="codigo_vendedor">Código do Vendedor:</label>
                                <input type="text" id="codigo_vendedor" name="codigo_vendedor" placeholder="Ex: 976" required>
                            </div>
                            
                            <div class="form-group">
                                <label for="observacao">Observação:</label>
                                <textarea id="observacao" name="observacao" placeholder="Descreva aqui suas observações sobre a inadimplência, ações tomadas, previsões de pagamento, etc..." required></textarea>
                            </div>
                            
                            <div class="form-group">
                                <label for="data_observacao">Data da Observação:</label>
                                <input type="date" id="data_observacao" name="data_observacao" value="{hoje.strftime('%Y-%m-%d')}" required>
                            </div>
                            
                            <button type="submit" class="btn-enviar">📤 Enviar Observação</button>
                        </form>
                    </div>
                    
                    <div class="observacoes-lista">
                        <h3>📋 Observações Registradas</h3>
                        <button class="btn-atualizar" onclick="atualizarObservacoes()">🔄 Atualizar Lista</button>
                        <div id="lista-observacoes">
        """
        
        # Adicionar observações existentes
        for obs in reversed(observacoes):  # Mais recentes primeiro
            data_obs = datetime.fromisoformat(obs['data_envio']).strftime('%d/%m/%Y às %H:%M')
            html_content += f"""
                            <div class="observacao-item">
                                <div class="observacao-header">
                                    <span class="observacao-vendedor">{obs['nome_vendedor']} (Código: {obs['codigo_vendedor']})</span>
                                    <span class="observacao-data">{data_obs}</span>
                                </div>
                                <div class="observacao-texto">{obs['observacao']}</div>
                            </div>
            """
        
        html_content += f"""
                        </div>
                    </div>
                </div>
                
                <div class="footer">
                    <p>Relatório gerado em {hoje.strftime('%d/%m/%Y às %H:%M')}</p>
                    <p>Sistema de Gestão de Inadimplência</p>
                </div>
            </div>
            
            <script>
            // Upload embutido no cabeçalho (evita f-string dentro do atributo onsubmit)
            (function(){{
                const form = document.getElementById('uploadFormInline');
                if (form) {{
                    form.addEventListener('submit', function(e) {{
                        e.preventDefault();
                        const fileInput = document.getElementById('arquivoInline');
                        if (!fileInput || fileInput.files.length === 0) {{
                            alert('Selecione um arquivo.');
                            return;
                        }}
                        const fd = new FormData(form);
                        fetch('/upload', {{ method: 'POST', body: fd }})
                            .then(r => r.json())
                            .then(d => {{ if (d.success) {{ location.reload(); }} else {{ alert('Erro: ' + d.error); }} }})
                            .catch(err => alert('Erro no upload: ' + err));
                    }});
                }}
            }})();
            function enviarObservacao(event) {{
                event.preventDefault();
                
                // Coletar dados do formulário
                const formData = new FormData(event.target);
                const dados = {{
                    nome_vendedor: formData.get('nome_vendedor'),
                    codigo_vendedor: formData.get('codigo_vendedor'),
                    observacao: formData.get('observacao'),
                    data_observacao: formData.get('data_observacao')
                }};
                
                // Enviar para o servidor
                fetch('/salvar_observacao', {{
                    method: 'POST',
                    headers: {{
                        'Content-Type': 'application/json',
                    }},
                    body: JSON.stringify(dados)
                }})
                .then(response => response.json())
                .then(data => {{
                    if (data.success) {{
                        alert('✅ Observação enviada com sucesso!');
                        event.target.reset();
                        atualizarObservacoes();
                    }} else {{
                        alert('❌ Erro ao enviar observação: ' + data.error);
                    }}
                }})
                .catch(error => {{
                    alert('❌ Erro ao enviar observação: ' + error);
                }});
            }}
            
            function atualizarObservacoes() {{
                location.reload();
            }}
            
            // Funções de filtro
            function aplicarFiltros() {{
                const vendedor = document.getElementById('filtro-vendedor').value;
                const status = document.getElementById('filtro-status').value;
                const dias = document.getElementById('filtro-dias').value;
                const valor = document.getElementById('filtro-valor').value;
                
                // Mostrar informações do filtro ativo
                let filtrosAtivos = [];
                if (vendedor) filtrosAtivos.push(`Vendedor: ${vendedor}`);
                if (status) filtrosAtivos.push(`Status: ${status}`);
                if (dias) filtrosAtivos.push(`Dias: ${dias}`);
                if (valor) filtrosAtivos.push(`Valor mínimo: R$ ${parseFloat(valor).toFixed(2)}`);
                
                const filtroInfo = document.getElementById('filtro-ativo-info');
                if (filtrosAtivos.length > 0) {{
                    filtroInfo.innerHTML = `<div class="filtro-ativo"><strong>Filtros Ativos:</strong> ${filtrosAtivos.join(' | ')}</div>`;
                    filtroInfo.style.display = 'block';
                }} else {{
                    filtroInfo.style.display = 'none';
                }}
                
                // Aplicar filtros nas tabelas
                filtrarTabelaResumo(vendedor, status, dias, valor);
                filtrarTabelaDetalhamento(vendedor, status, dias, valor);
            }}
            
            function limparFiltros() {{
                document.getElementById('filtro-vendedor').value = '';
                document.getElementById('filtro-status').value = '';
                document.getElementById('filtro-dias').value = '';
                document.getElementById('filtro-valor').value = '';
                document.getElementById('filtro-ativo-info').style.display = 'none';
                
                // Mostrar todas as linhas
                const tabelaResumo = document.getElementById('tabela-resumo');
                const tabelaDetalhamento = document.getElementById('tabela-detalhamento');
                
                if (tabelaResumo) {{
                    const linhasResumo = tabelaResumo.querySelectorAll('tbody tr');
                    linhasResumo.forEach(tr => {{
                        tr.style.display = '';
                    }});
                }}
                
                if (tabelaDetalhamento) {{
                    const linhasDetalhamento = tabelaDetalhamento.querySelectorAll('tbody tr');
                    linhasDetalhamento.forEach(tr => {{
                        tr.style.display = '';
                    }});
                }}
            }}
            
            function filtrarTabelaResumo(vendedor, status, dias, valor) {{
                const tabela = document.getElementById('tabela-resumo');
                const linhas = tabela.querySelectorAll('tbody tr');
                
                linhas.forEach(linha => {{
                    const colunas = linha.querySelectorAll('td');
                    if (colunas.length >= 8) {{
                        const codVendedor = colunas[0].textContent.trim();
                        const statusLinha = colunas[8].textContent.trim();
                        const diasMedio = parseFloat(colunas[7].textContent.replace(' dias', ''));
                        const valorTotal = parseFloat(colunas[2].textContent.replace('R$ ', '').replace('.', '').replace(',', '.'));
                        
                        let mostrar = true;
                        
                        if (vendedor && codVendedor !== vendedor) mostrar = false;
                        if (status && statusLinha !== status) mostrar = false;
                        if (dias && !filtrarPorDias(diasMedio, dias)) mostrar = false;
                        if (valor && valorTotal < parseFloat(valor)) mostrar = false;
                        
                        linha.style.display = mostrar ? '' : 'none';
                    }}
                }});
            }}
            
                         function filtrarTabelaDetalhamento(vendedor, status, dias, valor) {{
                 const tabelaDetalhamento = document.getElementById('tabela-detalhamento');
                 const linhas = tabelaDetalhamento.querySelectorAll('tbody tr');
                 
                 linhas.forEach(linha => {{
                     const colunas = linha.querySelectorAll('td');
                     if (colunas.length >= 6) {{
                         const nomeVendedor = colunas[2].textContent.trim();
                         // Extrair código do vendedor do nome (assumindo formato "Código - Nome")
                         let codVendedor = '';
                         if (nomeVendedor.includes(' - ')) {{
                             codVendedor = nomeVendedor.split(' - ')[0];
                         }} else {{
                             codVendedor = nomeVendedor.split(' ')[0];
                         }}
                         const statusLinha = colunas[6].textContent.trim();
                         const diasAtraso = parseFloat(colunas[5].textContent.replace(' dias', ''));
                         const valorTitulo = parseFloat(colunas[3].textContent.replace('R$ ', '').replace('.', '').replace(',', '.'));
                         
                         let mostrar = true;
                         
                         if (vendedor && codVendedor !== vendedor) mostrar = false;
                         if (status && statusLinha !== status) mostrar = false;
                         if (dias && !filtrarPorDias(diasAtraso, dias)) mostrar = false;
                         if (valor && valorTitulo < parseFloat(valor)) mostrar = false;
                         
                         linha.style.display = mostrar ? '' : 'none';
                     }}
                 }});
             }}
            
            function filtrarPorDias(dias, filtro) {{
                switch(filtro) {{
                    case '0-10': return dias >= 0 && dias <= 10;
                    case '11-30': return dias >= 11 && dias <= 30;
                    case '31-60': return dias >= 31 && dias <= 60;
                    case '60+': return dias > 60;
                    default: return true;
                }}
            }}
            
            // Auto-preenchimento do código do vendedor baseado na URL
            window.onload = function() {{
                const urlParams = new URLSearchParams(window.location.search);
                const vendedor = urlParams.get('vendedor');
                if (vendedor) {{
                    document.getElementById('codigo_vendedor').value = vendedor;
                    document.getElementById('filtro-vendedor').value = vendedor;
                    aplicarFiltros(); // Aplicar filtro automaticamente
                }}
            }};
            </script>
        </body>
        </html>
        """
        
        return html_content
        
    except Exception as e:
        logger.error(f"❌ Erro ao gerar HTML: {e}")
        return None

@app.route('/')
def relatorio_geral():
    """Página principal do relatório"""
    try:
        # Obter dados de inadimplência
        df_inadimplencia = obter_dados_inadimplencia()
        if df_inadimplencia is None:
            # Se não há dados, mostrar página de upload
            return gerar_pagina_upload()
        
        # Calcular métricas
        df_metricas = calcular_metricas_inadimplencia(df_inadimplencia)
        if df_metricas is None:
            return "❌ Erro ao calcular métricas", 500
        
        # Carregar observações
        observacoes = carregar_observacoes()
        
        # Gerar HTML
        html_content = gerar_html_relatorio(df_inadimplencia, df_metricas, observacoes)
        if html_content is None:
            return "❌ Erro ao gerar relatório", 500
        
        return html_content
        
    except Exception as e:
        logger.error(f"❌ Erro na página principal: {e}")
        return f"❌ Erro interno: {e}", 500

@app.route('/vendedor/<codigo>')
def relatorio_vendedor(codigo):
    """Relatório individual por vendedor"""
    return redirect(f'/?vendedor={codigo}')

@app.route('/salvar_observacao', methods=['POST'])
def salvar_observacao_route():
    """Salva uma nova observação"""
    try:
        dados = request.get_json()
        
        if not dados or not all(k in dados for k in ['nome_vendedor', 'codigo_vendedor', 'observacao', 'data_observacao']):
            return jsonify({'success': False, 'error': 'Dados incompletos'})
        
        # Salvar observação
        if salvar_observacao(dados):
            return jsonify({'success': True})
        else:
            return jsonify({'success': False, 'error': 'Erro ao salvar'})
            
    except Exception as e:
        logger.error(f"❌ Erro ao salvar observação: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/observacoes')
def listar_observacoes():
    """Lista todas as observações (para gestores)"""
    try:
        observacoes = carregar_observacoes()
        return jsonify(observacoes)
    except Exception as e:
        logger.error(f"❌ Erro ao listar observações: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/upload', methods=['POST'])
def upload_arquivo():
    """Upload do arquivo Excel"""
    try:
        if 'arquivo' not in request.files:
            return jsonify({'success': False, 'error': 'Nenhum arquivo selecionado'})
        
        arquivo = request.files['arquivo']
        if arquivo.filename == '':
            return jsonify({'success': False, 'error': 'Nenhum arquivo selecionado'})
        
        if arquivo and allowed_file(arquivo.filename):
            # Salvar arquivo
            filename = "RESUMO_VENDAS.xlsx"
            filepath = os.path.join(UPLOAD_FOLDER, filename)
            arquivo.save(filepath)
            
            logger.info(f"✅ Arquivo {filename} enviado com sucesso")
            return jsonify({'success': True, 'message': 'Arquivo enviado com sucesso!'})
        else:
            return jsonify({'success': False, 'error': 'Tipo de arquivo não permitido. Use .xlsx ou .xls'})
            
    except Exception as e:
        logger.error(f"❌ Erro no upload: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/download')
def download_template():
    """Download do template Excel"""
    try:
        # Criar um template básico se não existir
        template_path = os.path.join(UPLOAD_FOLDER, "TEMPLATE_RESUMO_VENDAS.xlsx")
        
        if not os.path.exists(template_path):
            # Criar DataFrame de exemplo
            df_exemplo = pd.DataFrame({
                'RCA': ['976', '515', '2493'],
                'VALOR': [1000.00, 2500.00, 1500.00],
                'DIAS': [15, 30, 45],
                'CLIENTE': ['Cliente A', 'Cliente B', 'Cliente C'],
                'VENC': ['2024-09-15', '2024-09-30', '2024-10-15'],
                'DUPLIC': ['001', '002', '003'],
                'NOME_RCA': ['João Silva', 'Maria Santos', 'Pedro Costa']
            })
            
            # Salvar como Excel
            df_exemplo.to_excel(template_path, sheet_name='BASE_INADI', index=False)
        
        return send_file(template_path, as_attachment=True, download_name="TEMPLATE_RESUMO_VENDAS.xlsx")
        
    except Exception as e:
        logger.error(f"❌ Erro ao gerar template: {e}")
        return jsonify({'error': str(e)}), 500

def abrir_navegador():
    """Abre o navegador automaticamente"""
    import time
    time.sleep(2)  # Aguarda o servidor iniciar
    webbrowser.open('http://localhost:5000')

if __name__ == '__main__':
    print("=" * 60)
    print("🚀 SERVIDOR DE RELATÓRIO DE INADIMPLÊNCIA")
    print("=" * 60)
    print("📊 Relatório geral: http://localhost:5000")
    print("👤 Relatório individual: http://localhost:5000/vendedor/976")
    print("📝 Observações: http://localhost:5000/observacoes")
    print("=" * 60)
    
    # Verificar se está em produção ou desenvolvimento
    import os
    port = int(os.environ.get('PORT', 5000))
    
    if os.environ.get('RENDER'):  # Está no Render
        print("🌐 Modo Produção - Render.com")
        app.run(host='0.0.0.0', port=port, debug=False)
    else:  # Modo desenvolvimento local
        print("💻 Modo Desenvolvimento Local")
        # Abrir navegador automaticamente
        threading.Thread(target=abrir_navegador, daemon=True).start()
        app.run(host='0.0.0.0', port=port, debug=False)
