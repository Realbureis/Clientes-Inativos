import streamlit as st
import pandas as pd
from urllib.parse import quote
from datetime import date, timedelta 
import datetime 
import io

# --- Configurações da Aplicação ---
st.set_page_config(layout="wide", page_title="Sistema de Segmentação: Inativos e Aceleração")

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
def process_data_segmentation(df_input):
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
    
    if df.empty:
        return pd.DataFrame(), pd.DataFrame(), metrics 
    
    # --- ETAPA 2: IDENTIFICAÇÃO DA COORTE BASE (Filtro 1: ÚNICO DIA) ---
    today = date.today() 
    date_28_days_ago = today - timedelta(days=28)
    
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
    
    # --- ETAPA 4: Geração dos DataFrames Finais (DFs de Referência de 28 dias) ---
    
    # 1. Base para DF de Mensagens (Apenas 1 linha por ID, que é a de 28 dias atrás)
    df_reference = df_coorte.sort_values(by=COL_DATE, ascending=False).drop_duplicates(subset=[COL_ID], keep='first').copy()
    
    # 2. Criar a mensagem na DF de Referência (Mensagem baseada no pedido de 28 dias atrás)
    def create_message(row):
        cliente_full_name = row[COL_NAME]
        detento_full_name = row[COL_DETENTO]
        last_order_date = row[COL_DATE].strftime('%d/%m/%Y') 
        client_first_name = str(cliente_full_name).strip().split(' ')[0].capitalize() 
        
        # Lógica de gênero
        if not detento_full_name or pd.isna(detento_full_name):
            detento_first_name = "a pessoa amada" 
            pronome = "ele/ela" 
            artigo_definido = "o/a"
        else:
            detento_first_name = str(detento_full_name).strip().split(' ')[0].capitalize()
            gender_parts = get_gender_parts(detento_first_name) 
            pronome = gender_parts['pronome']
            artigo_definido = gender_parts['article'] 

        # --- TEMPLATE DE MENSAGEM FINAL (CONSULTIVA) ---
        message = (
            f"Olá {client_first_name}! Aqui é a Sofia, sua consultora exclusiva da Jumbo CDP!\n\n"
            f"Percebi que o seu último jumbo para {artigo_definido} {detento_first_name} foi em {last_order_date}, então resolvi falar com você.\n\n"
            f"Quero garantir que {pronome} não fique sem os itens que precisa!\n\n"
            f"Você conseguiu identificar algum motivo para a pausa no envio? Estou aqui para te ajudar com o que precisar.\n\n"
            f"Conte comigo! 💛"
        )
        return client_first_name, message

    df_reference[COL_NAME] = df_reference[COL_NAME].astype(str).fillna('')
    data_series = df_reference.apply(create_message, axis=1)
    temp_df = pd.DataFrame(data_series.tolist(), index=df_reference.index) 
    df_reference[COL_OUT_NAME] = temp_df[0]
    df_reference[COL_OUT_MSG] = temp_df[1]
    
    # Colunas de referência
    ref_cols_to_merge = [COL_ID, COL_PHONE, COL_OUT_NAME, COL_OUT_MSG, COL_DATE, COL_ORDER_ID] 

    # --- ETAPA 5: CRIAÇÃO DO DATAFRAME DE SAÍDA COMPLETO (Todas as Linhas) ---

    # A. Reduzir o DF completo da coorte apenas para os IDs qualificados
    df_full_output = df_coorte[df_coorte[COL_ID].isin(aceleracao_set)].copy()

    # B. Renomear colunas do lado esquerdo (pedido específico) antes de fazer o merge
    df_full_output.rename(columns={
        COL_DATE: COL_DATE + '_pedido',
        COL_ORDER_ID: COL_ORDER_ID + '_pedido',
        COL_STATUS: COL_STATUS + '_pedido',
        COL_TOTAL_VALUE: COL_TOTAL_VALUE + '_pedido'
    }, inplace=True)
    
    # C. Merge dos dados de todas as linhas (df_full_output) com os dados de referência/mensagem (df_reference)
    df_processed = df_full_output.merge(df_reference[ref_cols_to_merge], on=COL_ID, how='left').copy()
    
    # D. Finalização das Métricas
    metrics['clientes_qualificados'] = len(df_reference) # O número de IDs únicos qualificados
    
    if df_processed.empty:
        return df_processed, metrics 

    # 7. Formatar colunas para exibição
    def format_brl(value):
        try:
            value_str = str(value).replace('R$', '').replace('.', '').replace(',', '.')
            return f"R$ {float(value_str):.2f}".replace('.', ',')
        except:
            return str(value)

    df_processed['Valor_BRL'] = df_processed[COL_TOTAL_VALUE + '_pedido'].apply(format_brl)
    df_processed['Data_Referencia'] = df_processed[COL_DATE + '_pedido'].dt.strftime('%d/%m/%Y')
    
    return df_processed, metrics


# --- Interface do Usuário (Streamlit) ---

# Seção de Upload
st.header("1. Upload do Relatório de Vendas (Excel/CSV)")
st.markdown(f"#### Colunas Esperadas: {COL_ID}, {COL_NAME}, {COL_PHONE}, {COL_STATUS}, {COL_ORDER_ID}, **{COL_DATE}**, {COL_TOTAL_VALUE}, **{COL_DETENTO}**")

uploaded_file = st.file_uploader(
    "Arraste ou clique para enviar o arquivo.", 
    type=["csv", "xlsx"]
)

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


    # Botão de Processamento
    st.header("2. Iniciar Qualificação de Leads de Aceleração")
    if st.button("🚀 Processar Dados e Gerar Leads de Aceleração"):
        
        try:
            df_processed, metrics = process_data_aceleracao_v2(df_original) 
        except ValueError as ve:
            st.error(f"Erro de Processamento: {ve}")
            st.stop()
        
        # --- Seção de Resultados ---
        st.header("3. Lista de Disparo (Aceleração de Repetição)")
        
        col_met1, col_met2 = st.columns(2)
        col_met1.metric("Clientes Únicos Qualificados", metrics['clientes_qualificados'])
        col_met2.metric("Total de Linhas no Relatório", len(df_processed))
        
        total_ready = metrics['clientes_qualificados']

        st.subheader(f"Leads para Aceleração ({total_ready} Clientes Únicos)")
        st.markdown("---")

        if total_ready == 0:
            st.info("Nenhum lead encontrado com o perfil: Última Compra Enviada EXATAMENTE 28 dias atrás E Houve Nova Interação.")
        else:
            
            # Funções Auxiliares para Exibir Tabela e Botões (Cor Verde)
            
            def render_lead_table(df_display, title, color_code):
                st.subheader(f"✅ {title}")
                st.markdown("---")

                # Headers
                col_headers = st.columns([1.5, 1.2, 1.2, 1.2, 1.5, 5]) 
                col_headers[0].markdown("**Cliente (ID)**") 
                col_headers[1].markdown(f"**Data do Pedido**") 
                col_headers[2].markdown(f"**N. Pedido**") 
                col_headers[3].markdown(f"**{COL_TOTAL_VALUE}**") 
                col_headers[4].markdown(f"**Status da Linha**") 
                col_headers[5].markdown("**Ação (Disparo)**")
                st.markdown("---")

                current_client_id = None
                
                for index, row in df_display.iterrows():
                    cols = st.columns([1.5, 1.2, 1.2, 1.2, 1.5, 5]) 
                    
                    # Dados do Pedido (colunas _pedido)
                    pedido_status = row[COL_STATUS + '_pedido']
                    pedido_data = row['Data_Referencia']
                    pedido_valor = row['Valor_BRL']
                    pedido_numero = row[COL_ORDER_ID + '_pedido']
                    client_id = row[COL_ID]

                    # Dados de Referência (Mensagem/Nome/Telefone)
                    cliente_first_name = row[COL_OUT_NAME]
                    message_text = row[COL_OUT_MSG]
                    phone_number = "".join(filter(str.isdigit, str(row[COL_PHONE])))
                    
                    
                    # Checagem para renderizar o botão (apenas uma vez por cliente)
                    is_first_row_for_client = (client_id != current_client_id)
                    current_client_id = client_id
                    
                    # 1. Exibe os dados (mostra o nome apenas na primeira linha do ID)
                    if is_first_row_for_client:
                        cols[0].write(f"**{cliente_first_name}** ({client_id})")
                        
                        encoded_message = quote(message_text)
                        whatsapp_link = f"https://wa.me/55{phone_number}?text={encoded_message}"

                        whatsapp_button_html = f"""
                        <a href="{whatsapp_link}" target="_blank" style="
                            display: inline-block; 
                            padding: 8px 12px; 
                            background-color: {color_code}; 
                            color: white; 
                            border-radius: 4px; 
                            border: 1px solid #128C7E;
                            text-decoration: none;
                            cursor: pointer;
                            white-space: nowrap;
                        ">
                        ▶️ WhatsApp
                        </a>
                        """
                        cols[5].markdown(whatsapp_button_html, unsafe_allow_html=True) 
                    else:
                        cols[0].write(f"({client_id})")


                    cols[1].write(pedido_data)
                    cols[2].write(pedido_numero)
                    cols[3].write(pedido_valor)
                    cols[4].markdown(f"*{pedido_status}*") 
                    
                st.markdown("---")

            
            # --- Renderizar Segmento Único ---
            render_lead_table(df_processed, "Relatório Detalhado", "#25D366") 

            # --- Botão de Download ---
            df_export_combined = df_processed[[COL_ID, COL_NAME, COL_DETENTO, COL_PHONE, COL_STATUS + '_pedido', COL_ORDER_ID + '_pedido', COL_TOTAL_VALUE + '_pedido', 'Data_Referencia', COL_OUT_MSG]].copy()

            df_export_combined.rename(
                columns={
                    COL_STATUS + '_pedido': COL_STATUS, 
                    COL_ORDER_ID + '_pedido': COL_ORDER_ID, 
                    COL_TOTAL_VALUE + '_pedido': COL_TOTAL_VALUE, 
                    'Data_Referencia': 'Data do Pedido', 
                    COL_OUT_MSG: 'Mensagem_Referencia'
                },
                inplace=True)
            
            csv_data = df_export_combined.to_csv(index=False, sep=';', encoding='utf-8').encode('utf-8')
            st.download_button(
                label="📥 Baixar Lista de Aceleração Detalhada (CSV)",
                data=csv_data,
                file_name='clientes_aceleracao_detalhado.csv',
                mime='text/csv',
            )
