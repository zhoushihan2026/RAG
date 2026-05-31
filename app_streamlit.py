import streamlit as st
from pathlib import Path
from src.pipeline import Pipeline, hybrid_bm25_vector_config
import json

root_path = Path("data/stock_data")
pipeline = Pipeline(root_path, run_config=hybrid_bm25_vector_config)

st.set_page_config(page_title="RAG 企业知识库问答系统", layout="wide", page_icon="")

st.markdown("""
<style>
    /* 全局样式 */
    .main {
        background: #ebebed;
        padding: 20px;
    }
    
    /* 顶部导航栏 */
    .top-nav {
        background: #f5f5f7;
        padding: 16px 24px;
        border-radius: 12px;
        margin-bottom: 20px;
        display: flex;
        align-items: center;
        justify-content: space-between;
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06);
    }
    .top-nav h1 {
        color: #1a1a2e;
        margin: 0;
        font-size: 20px;
        font-weight: 600;
    }
    .top-nav .subtitle {
        color: #888;
        font-size: 13px;
    }
    
    /* 左侧边栏样式 */
    .sidebar-card {
        background: #f5f5f7;
        border-radius: 12px;
        padding: 20px;
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06);
        margin-bottom: 16px;
    }
    .sidebar-card h3 {
        color: #1a1a2e;
        font-size: 15px;
        font-weight: 600;
        padding-top: 10px;
        padding-bottom: 0px;
        border-bottom: 1px solid #f0f0f0;
    }
    
    /* 右侧内容区卡片 */
    .content-card {
        background: #f5f5f7;
        border-radius: 12px;
        padding: 24px;
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06);
        margin-bottom: 16px;
    }
    
    /* 最终答案 - 深色卡片 */
    .answer-card {
        background: #1a1a2e;
        border-radius: 12px;
        padding: 24px;
        color: #f0f0f0;
        font-size: 16px;
        line-height: 1.8;
        margin-bottom: 16px;
    }
    
    /* 区块标题 */
    .section-title {
        font-size: 15px;
        font-weight: 600;
        color: #1a1a2e;
        margin: 0 0 12px 0;
        padding-bottom: 8px;
        border-bottom: 1px solid #e0e0e0;
    }
    
    /* 区块标题（非第一个） */
    .section-title + .section-title {
        margin-top: 20px;
    }
    
    /* 推理过程 */
    .reasoning-card {
        background: #f7f7f8;
        border-radius: 10px;
        padding: 16px 20px;
        font-size: 14px;
        line-height: 1.8;
        color: #333;
        margin-bottom: 12px;
    }
    
    /* 推理摘要 */
    .summary-card {
        background: #f0f4f8;
        border-radius: 10px;
        padding: 16px 20px;
        font-size: 14px;
        line-height: 1.7;
        color: #333;
        margin-bottom: 12px;
    }
    
    /* 页码标签 */
    .page-tag {
        display: inline-block;
        background: #e8e8e8;
        color: #333;
        padding: 4px 12px;
        border-radius: 6px;
        font-size: 13px;
        margin: 3px 4px;
    }
    
    /* 按钮样式 */
    div.stButton > button {
        background: #1a1a2e;
        color: white;
        border: none;
        border-radius: 8px;
        padding: 10px 24px;
        font-size: 14px;
        font-weight: 500;
        width: 100%;
    }
    div.stButton > button:hover {
        background: #2d2d4e;
    }
    
    /* 欢迎页 */
    .welcome-card {
        background: #ffffff;
        border-radius: 12px;
        padding: 60px 40px;
        text-align: center;
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06);
    }
    .welcome-card h3 {
        color: #666;
        font-weight: 500;
        margin-bottom: 8px;
    }
    .welcome-card p {
        color: #999;
        font-size: 14px;
    }
    
    /* 配置信息 */
    .config-info {
        font-size: 12px;
        color: #888;
        line-height: 1.8;
    }
    .config-info strong {
        color: #555;
    }
    
    /* 隐藏 Streamlit 默认样式 */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
</style>
""", unsafe_allow_html=True)

# 顶部导航栏
st.markdown("""
<div class="top-nav">
    <div>
        <h1>RAG 企业知识库问答系统</h1>
    </div>
</div>
""", unsafe_allow_html=True)

# 左右两栏布局
col_left, col_right = st.columns([1, 3])

with col_left:
    st.markdown("""
    <div class="sidebar-card">
        <h3>查询设置</h3>
        <div style="margin-top: 12px;">
    </div>
    """, unsafe_allow_html=True)
    
    user_question = st.text_area("", "中芯国际在晶圆制造行业中的地位如何？", height=120, label_visibility="collapsed")
    submit_btn = st.button("生成答案", use_container_width=True)
    
    st.markdown("""
        </div>
    </div>
    """, unsafe_allow_html=True)
    
    # 文件上传区域
    st.markdown("""
    <div class="sidebar-card" style="margin-top: 16px;">
        <h3>文档上传</h3>
        <div style="margin-top: 12px;">
    </div>
    """, unsafe_allow_html=True)
    
    uploaded_file = st.file_uploader("上传PDF文件", type=["pdf"], label_visibility="collapsed")
    
    if uploaded_file:
        # 显示上传的文件名
        file_name = uploaded_file.name
        st.markdown(f'<div style="font-size:13px; color:#555; margin-bottom:8px;">已选择: {file_name}</div>', unsafe_allow_html=True)
        
        upload_btn = st.button("添加到数据库", use_container_width=True, key="upload_btn")
        
        if upload_btn:
            import tempfile as _tempfile
            import os as _os
            
            with _tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                tmp.write(uploaded_file.getvalue())
                tmp_path = tmp.name
            
            try:
                with st.spinner("正在处理文件，请稍候..."):
                    progress_bar = st.progress(0, text="准备处理文件...")
                    
                    progress_bar.progress(10, text="正在解析PDF...")
                    upload_status = pipeline.process_single_pdf_file(tmp_path, original_filename=file_name)
                    
                    progress_bar.progress(100, text="处理完成")
                
                if upload_status["status"] == "exists":
                    st.success(upload_status["message"])
                elif upload_status["status"] == "success":
                    st.success(upload_status["message"])
                else:
                    st.error(upload_status["message"])
                    
            except Exception as e:
                st.error(f"处理出错: {str(e)}")
            finally:
                progress_bar.empty()
                if _os.path.exists(tmp_path):
                    _os.remove(tmp_path)
    
    st.markdown("""
        </div>
    </div>
    """, unsafe_allow_html=True)

with col_right:
    if submit_btn and user_question.strip():
        # 状态栏
        status_placeholder = st.empty()
        status_placeholder.info("正在检索相关文档...")

        try:
            stream_gen = pipeline.answer_single_question_stream(user_question, kind="string")

            # 先显示答案区域标题
            # st.markdown('<div class="content-card">', unsafe_allow_html=True)
            st.markdown('<div class="section-title">最终答案</div>', unsafe_allow_html=True)

            # 流式输出区域
            answer_placeholder = st.empty()
            collected_text = ""
            display_text = ""
            answer_dict = None
            in_final_answer = False
            fa_buffer = ""

            for event in stream_gen:
                event_type = event["type"]
                event_content = event["content"]

                if event_type == "status":
                    status_placeholder.info(event_content)
                elif event_type == "error":
                    status_placeholder.empty()
                    st.error(event_content)
                    break
                elif event_type == "stream_start":
                    status_placeholder.info("正在生成回答...")
                elif event_type == "token":
                    collected_text += event_content
                    # 尝试从流式文本中提取final_answer内容
                    lower_text = collected_text.lower()
                    fa_key = '"final_answer"'
                    fa_idx = lower_text.find(fa_key)
                    if fa_idx != -1:
                        after_key = collected_text[fa_idx + len(fa_key):]
                        # 跳过冒号和引号
                        stripped = after_key.lstrip()
                        if stripped.startswith(':'):
                            stripped = stripped[1:].lstrip()
                        if stripped.startswith('"'):
                            content_start = after_key.find('"') + 1
                            # 查找结束引号（考虑转义）
                            end_idx = content_start
                            while end_idx < len(after_key):
                                if after_key[end_idx] == '"' and (end_idx == 0 or after_key[end_idx-1] != '\\'):
                                    break
                                end_idx += 1
                            display_text = after_key[content_start:end_idx]
                            # 处理转义字符
                            display_text = display_text.replace('\\"', '"').replace('\\n', '\n').replace('\\\\', '\\')
                        else:
                            display_text = collected_text
                    else:
                        # 还没到final_answer字段，不显示
                        display_text = ""

                    if display_text:
                        answer_placeholder.markdown(
                            f'<div class="answer-card">{display_text}</div>',
                            unsafe_allow_html=True
                        )
                elif event_type == "done":
                    answer_dict = event_content
                    final_answer = answer_dict.get("final_answer", display_text or collected_text)
                    answer_placeholder.markdown(
                        f'<div class="answer-card">{final_answer}</div>',
                        unsafe_allow_html=True
                    )
                    status_placeholder.empty()

            # 流式结束后，展示其他信息
            if answer_dict:
                step_by_step = answer_dict.get("step_by_step_analysis", "-")
                reasoning_summary = answer_dict.get("reasoning_summary", "-")
                relevant_pages = answer_dict.get("relevant_pages", [])
                source_files = answer_dict.get("source_files", {})
                references = answer_dict.get("references", [])

                # 推理过程
                if step_by_step and step_by_step != "-":
                    st.markdown('<div class="section-title">推理过程</div>', unsafe_allow_html=True)
                    st.markdown(f'<div class="reasoning-card">{step_by_step}</div>', unsafe_allow_html=True)

                # 推理摘要
                if reasoning_summary and reasoning_summary != "-":
                    st.markdown('<div class="section-title">推理摘要</div>', unsafe_allow_html=True)
                    st.markdown(f'<div class="summary-card">{reasoning_summary}</div>', unsafe_allow_html=True)

                # 参考来源
                st.markdown('<div class="section-title">参考来源</div>', unsafe_allow_html=True)

                if references:
                    sources_html = ""
                    seen_sources = set()
                    for ref in references:
                        pdf_sha1 = ref.get("pdf_sha1", "")
                        page_idx = ref.get("page_index", -1)
                        source_file = ref.get("source_file", "")
                        file_info = source_files.get(pdf_sha1, {})
                        file_name = file_info.get("file_name", source_file or pdf_sha1)

                        if file_name:
                            import os as _os
                            short_name = _os.path.splitext(_os.path.basename(file_name))[0]
                        else:
                            short_name = pdf_sha1

                        source_key = f"{short_name}_p{page_idx}"
                        if source_key not in seen_sources:
                            seen_sources.add(source_key)
                            sources_html += f'<span class="page-tag">{short_name} - Page {page_idx}</span> '
                    if sources_html:
                        st.markdown(f'<div style="padding:4px 0;">{sources_html}</div>', unsafe_allow_html=True)
                    else:
                        st.markdown('<div style="color:#999; padding:4px 0;">无参考来源信息</div>', unsafe_allow_html=True)
                elif relevant_pages:
                    pages_html = " ".join([f'<span class="page-tag">Page {p}</span>' for p in relevant_pages])
                    st.markdown(f'<div style="padding:4px 0;">{pages_html}</div>', unsafe_allow_html=True)
                else:
                    st.markdown('<div style="color:#999; padding:4px 0;">无参考来源信息</div>', unsafe_allow_html=True)

            st.markdown('</div>', unsafe_allow_html=True)

        except Exception as e:
            status_placeholder.empty()
            st.error(f"生成答案时出错: {e}")
    else:
        # st.markdown('<div class="content-card" style="padding: 20px;">', unsafe_allow_html=True)
        st.markdown("""
        <div class="welcome-card" style="background: transparent; box-shadow: none; padding: 0;">
            <h3>请在左侧输入问题并点击 [生成答案]</h3>
            <p>系统将基于企业年报知识库进行检索和回答</p>
        </div>
        """, unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)
