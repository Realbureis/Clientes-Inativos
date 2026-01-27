import streamlit as st
import pandas as pd
from urllib.parse import quote
from datetime import date, timedelta 
import datetime 
import io

# --- Configurações da Aplicação ---
st.set_page_config(layout="wide", page_title="Sistema de Segmentação: Inativos e Aceleração V7")

st.title("🎯 Qualificação para Aceleração de Repetição (28 Dias + Intenção)")
st.markdown("Divide a coorte de clientes cuja **ÚLTIMA atividade geral** foi **exatamente 28 dias atrás** em dois grupos para ações de venda distintas.")

# --- Definição das Colunas ---
COL_ID = 'Codigo Cliente'
COL_NAME = 'Cliente'
COL_PHONE = 'Fone Fixo'
COL_STATUS = 'Status' 
COL_ORDER_ID = 'N. Pedido' 
COL_DATE = 'Data' 
COL_TOTAL_VALUE = 'Valor Total' 
COL_DETENTO = 'Ultimo Detento Cadastrado' 

# Colunas de SAÍDA
COL_OUT_NAME = 'Cliente_Formatado'
COL_OUT_MSG = 'Mensagem_Personalizada'

# --- Lógica de Gênero ---
FEMININE_NAMES = {
    'maria', 'ana', 'paula', 'carla', 'patricia', 'gabriela', 'juliana', 
    'fernanda', 'aline', 'bruna', 'camila', 'leticia', 'isabela', 'sofia', 
    'beatriz', 'vitoria', 'claudia', 'elena', 'raquel', 'sandra', 'valeria',
    'marcia', 'monica', 'larissa', 'eduarda', 'helena', 'regina', 'viviane', 'luciana'
}

def get_gender_parts(first_name):
    """Retorna o pronome, preposição e artigo definido com base no primeiro nome."""
    lower_name = first_name.lower()
    
    if lower_name in FEMININE_NAMES or (lower_name.endswith('a') and len(lower_name) > 2):
        return {'pronome': 'ela', 'preposicao': 'da', 'article': 'a'}
    
    return {'pronome': 'ele', 'preposicao': 'do', 'article': 'o'}


# --- Função de Lógica de Negócio (O Cérebro) ---

@st.cache_data
def process_data_aceleracao_v2(df_input, date_28_days_ago):
    """
    Segmenta a coorte de clientes cuja última atividade foi há 28 dias em
    "Aceleração" (com histórico de intenção) e "Puros Inativos" (sem histórico de intenção).
    """
    df_original = df_input.copy() 
    
    # 1. Checagem de colunas obrigatórias
    required_cols = [COL_ID, COL_NAME, COL_PHONE, COL_STATUS, COL_ORDER_ID, COL_DATE, COL_TOTAL_VALUE, COL_DETENTO]
    if not all(col in df_original.columns for col in required_cols):
        missing = [col for col in required_cols if col not in df_original.columns]
        raise ValueError(f"O arquivo está faltando as seguintes colunas obrigatórias: {', '.join(missing)}. Verifique '{COL_DETENTO}'.")

    metrics = {
        'original_count': len(df_original),
        'removidos_cancelados': 0,
        'coorte_28_dias': 0,
        'aceleracao_count': 0,
        'puros_inativos_count': 0
    }
    
    # 2. Conversão da Data
    try:
        df_original[COL_DATE] = pd.to_datetime(df_original[COL_DATE], errors='coerce', dayfirst=True).dt.normalize()
    except Exception as e:
        raise ValueError(f"Erro ao converter a coluna '{COL_DATE}' para data. Erro: {e}")
    
    df_original.dropna(subset=[COL_DATE], inplace=True)
    
    # --- ETAPA 1: FILTRO DE EXCLUSÃO (CANCELAMENTO) ---
    df = df_original.copy()
    cancelados_ids = df[df[COL_STATUS].astype(str).str.lower() == 'cancelado'][COL_ID].unique()
    df = df[~df[COL_ID].isin(cancelados_ids)].copy()
    metrics['removidos_cancelados'] = metrics['original_count'] - len(df)
    
    # GARANTIA DE COMPRADOR (Cliente deve ter tido um "Enviado" alguma vez)
    comprador_ids = df[df[COL_STATUS].astype(str).str.lower() == 'enviado'][COL_ID].unique()
    df = df[df[COL_ID].isin(comprador_ids)].copy()
    
    if df.empty:
        return pd.DataFrame(), pd.DataFrame(), metrics 
    
    # --- ETAPA 2: IDENTIFICAÇÃO DA COORTE BASE (Filtro 1: ÚNICO DIA) ---
    
    # A. Encontra a ÚLTIMA DATA de atividade (qualquer status) para cada cliente
    df_last_activity = df.groupby(COL_ID)[COL_DATE].max().reset_index()
    
    # B. Filtra: A última atividade geral DEVE ser de EXATAMENTE 28 dias atrás.
    coorte_28_dias_ids = df_last_activity[
        df_last_activity[COL_DATE].dt.date == date_28_days_ago
    ][COL_ID].unique()
    
    metrics['coorte_28_dias'] = len(coorte_28_dias_ids)
    
    if len(coorte_28_dias_ids) == 0:
        return pd.DataFrame(), pd.DataFrame(), metrics

    # C. Reduzimos o DataFrame apenas aos clientes que estão nessa coorte
    df_coorte = df[df[COL_ID].isin(coorte_28_dias_ids)].copy()

    # --- ETAPA 3: SEGMENTAÇÃO POR INTENÇÃO (Filtro 2: HISTÓRICO) ---
    
    # A. Define os status que indicam alta intenção (perfil)
    status_alta_intencao = ['aguardando pagamento', 'pedido salvo', 'pagamento efetuado'] 
    
    # B. Dentro DESSA coorte de 28 dias, identifica QUEM tem qualquer pedido com status de alta intenção.
    aceleracao_ids = df_coorte[
        df_coorte[COL_STATUS].astype(str).str.lower().isin(status_alta_intencao)
    ][COL_ID].unique()
    
    # C. Segmentação
    aceleracao_set = set(aceleracao_ids)
    puros_inativos_set = set(coorte_28_dias_ids) - aceleracao_set 
    
    # --- ETAPA 4: Geração dos DFs de Referência ---
    
    df_reference = df_coorte.sort_values(by=COL_DATE, ascending=False).drop_duplicates(subset=[COL_ID], keep='first').copy()
    
    def create_message(row):
        cliente_full_name = row[COL_NAME]
        detento_full_name = row[COL_DETENTO]
        last_order_date = row[COL_DATE].strftime('%d/%m/%Y') 
        client_first_name = str(cliente_full_name).strip().split(' ')[0].capitalize() 
        
        # Lógica de gênero do detento
        if not detento_full_name or pd.isna(detento_full_name):
            detento_first_name = "seu familiar" 
            artigo_definido = "o/a"
        else:
            detento_first_name = str(detento_full_name).strip().split(' ')[0].capitalize()
            gender_parts = get_gender_parts(detento_first_name) 
            artigo_definido = gender_parts['article'] 

        # --- NOVA MENSAGEM PERSONALIZADA (SEM NATAL) ---
        message = (
            f"Olá, *{client_first_name}!* Aqui é a Tais, sua consultora exclusiva da Jumbo CDP!\n\n"
            f"Percebi que o seu último jumbo para o *{artigo_definido}* *{detento_first_name}* foi em *{last_order_date}*.\n\n"
            f"Resolvi falar com você para garantir que ele não fique *muito tempo sem os itens essenciais*!\n\n"
            f"*Conte comigo para cuidar de vocês!*"
        )
        return client_first_name, message

    df_reference[COL_NAME] = df_reference[COL_NAME].astype(str).fillna('')
    data_series = df_reference.apply(create_message, axis=1)
    temp_df = pd.DataFrame(data_series.tolist(), index=df_reference.index) 
    df_reference[COL_OUT_NAME] = temp_df[0]
    df_reference[COL_OUT_MSG] = temp_df[1]
    
    # Segmentação final dos DFs
    df_aceleracao_final = df_reference[df_reference[COL_ID].isin(aceleracao_set)].copy()
    df_puros_inativos_final = df_reference[df_reference[COL_ID].isin(puros_inativos_set)].copy()
    
    metrics['aceleracao_count'] = len(aceleracao_set)
    metrics['puros_inativos_count'] = len(puros_inativos_set)
    
    def format_df(df_in, segment_name):
        if df_in.empty:
            return df_in
            
        def format_brl(value):
            try:
                value_str = str(value).replace('R$', '').replace('.', '').replace(',', '.')
                return f"R$ {float(value_str):.2f}".replace('.', ',')
            except:
                return str(value)

        df_in['Valor_BRL'] = df_in[COL_TOTAL_VALUE].apply(format_brl)
        df_in['Data_Referencia'] = df_in[COL_DATE].dt.strftime('%d/%m/%Y')
        df_in['Status_Segmento'] = segment_name
        
        return df_in.sort_values(by=COL_ID, ascending=True).reset_index(drop=True)

    df_aceleracao_final = format_df(df_aceleracao_final, 'ACELERAÇÃO (INTENÇÃO)')
    df_puros_inativos_final = format_df(df_puros_inativos_final, 'PURO INATIVO (REENG.)')

    return df_aceleracao_final, df_puros_inativos_final, metrics


# --- Interface do Usuário (Streamlit) ---

today = date.today() 
date_28_days_ago = today - timedelta(days=28)

st.header("1. Upload do Relatório de Vendas (Excel/CSV)")
st.markdown(f"#### Data de Corte (28 dias atrás): **{date_28_days_ago.strftime('%d/%m/%Y')}**")

uploaded_file = st.file_uploader("Arraste ou clique para enviar o arquivo.", type=["csv", "xlsx"])

if uploaded_file is not None:
    try:
        if uploaded_file.name.endswith('.csv'):
            df_original = pd.read_csv(uploaded_file)
        else:
            df_original = pd.read_excel(uploaded_file, engine='openpyxl')
        st.success(f"Arquivo '{uploaded_file.name}' carregado com sucesso!")
    except Exception as e:
        st.error(f"Erro ao ler o arquivo. Erro: {e}")
        st.stop()

    st.header("2. Iniciar Segmentação dos Leads")
    if st.button("🚀 Processar Dados e Gerar Segmentos de 28 Dias"):
        try:
            df_aceleracao, df_puros_inativos, metrics = process_data_aceleracao_v2(df_original, date_28_days_ago) 
        except ValueError as ve:
            st.error(f"Erro de Processamento: {ve}")
            st.stop()
        
        st.header("3. Resultados da Segmentação")
        
        col_met1, col_met2, col_met3 = st.columns(3)
        col_met1.metric("Coorte Total (28 Dias)", metrics['coorte_28_dias'])
        col_met2.metric("Leads de Aceleração (Intenção)", metrics['aceleracao_count'])
        col_met3.metric("Leads Puros Inativos (Reeng.)", metrics['puros_inativos_count'])
        
        total_ready = metrics['aceleracao_count'] + metrics['puros_inativos_count']

        if total_ready == 0:
            st.info("Nenhum lead encontrado na coorte de 28 dias.")
        else:
            def render_lead_table(df_display, title, color_code):
                st.subheader(f"✅ {title}")
                st.markdown("---")
                
                for index, row in df_display.iterrows():
                    cols = st.columns([2, 1, 1, 1, 1, 3]) 
                    
                    cliente_first_name = row[COL_OUT_NAME]
                    client_id = row[COL_ID]
                    pedido_data = row['Data_Referencia']
                    pedido_numero = row[COL_ORDER_ID]
                    pedido_valor = row['Valor_BRL']
                    pedido_status = row[COL_STATUS]
                    message_text = row[COL_OUT_MSG]
                    phone_number = "".join(filter(str.isdigit, str(row[COL_PHONE])))
                    
                    cols[0].write(f"**{cliente_first_name}** ({client_id})")
                    cols[1].write(pedido_data)
                    cols[2].write(pedido_numero)
                    cols[3].write(pedido_valor)
                    cols[4].markdown(f"*{pedido_status}*") 

                    encoded_message = quote(message_text)
                    whatsapp_link = f"https://wa.me/55{phone_number}?text={encoded_message}"
                    
                    whatsapp_button_html = f"""
                    <a href="{whatsapp_link}" target="_blank" style="
                        display: inline-block; padding: 8px 12px; 
                        background-color: {color_code}; color: white; 
                        border-radius: 4px; text-decoration: none;
                        font-weight: bold; border: 1px solid #128C7E;">
                    ▶️ WhatsApp
                    </a>
                    """
                    cols[5].markdown(whatsapp_button_html, unsafe_allow_html=True) 

            if not df_aceleracao.empty:
                render_lead_table(df_aceleracao, "Segmento A: Leads de ACELERAÇÃO", "#25D366") 
            if not df_puros_inativos.empty:
                render_lead_table(df_puros_inativos, "Segmento B: Leads PUROS INATIVOS", "#34B7F1")
