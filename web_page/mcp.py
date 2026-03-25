import streamlit as st
import streamlit_antd_components as sac


def mcp_page():
    """
    MCP管理页面 - 纯UI设计代码
    使用Streamlit原生组件实现美观界面
    """

    # 页面标题区域
    st.markdown("<h1 style='font-size: 36px;'> 连接器管理</h1>", unsafe_allow_html=True)
    st.caption("配置和管理您的MCP连接器")

    st.divider()

    # 通用设置区域
    with st.expander("⚙️ 通用设置", expanded=True):
        st.subheader("基础配置")

        # 配置选项
        col1, col2 = st.columns(2)
        with col1:
            timeout = st.slider(
                "默认超时时间（秒）",
                min_value=10,
                max_value=300,
                value=30,
                step=5,
                help="连接器的默认超时时间设置"
            )

        with col2:
            working_dir = st.text_input(
                "工作目录",
                value="/app",
                help="连接器的工作目录路径"
            )

        # 环境变量配置
        st.subheader("环境变量配置")
        st.info("为连接器配置运行环境变量")

        # 示例环境变量
        env_col1, env_col2, env_col3 = st.columns([2, 3, 1])
        with env_col1:
            st.text_input("变量名", value="PATH", key="env_key_1")
        with env_col2:
            st.text_input("变量值", value="/usr/local/bin:/usr/bin:/bin", key="env_value_1")
        with env_col3:
            st.button("🗑️", key="del_env_1", use_container_width=True)

        # 操作按钮
        col_save, col_reset, _ = st.columns([1, 1, 2])
        with col_save:
            st.button("💾 保存设置", type="primary", use_container_width=True)
        with col_reset:
            st.button("🔄 重置默认", use_container_width=True)

    st.divider()

    # 已启用连接器区域
    st.subheader("✅ 已启用连接器")

    # 已启用连接器卡片
    enabled_col1, enabled_col2, enabled_col3 = st.columns([3, 1, 1])

    with enabled_col1:
        with st.container(border=True):
            # 连接器信息
            info_col1, info_col2 = st.columns([1, 4])
            with info_col1:
                st.markdown("""
                <div style='
                    background: linear-gradient(135deg, #4F46E5, #818CF8);
                    color: white;
                    width: 50px;
                    height: 50px;
                    border-radius: 12px;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    font-weight: bold;
                    font-size: 18px;
                '>S</div>
                """, unsafe_allow_html=True)

            with info_col2:
                st.markdown("**示例连接器**")
                st.caption("Stdio传输 · 运行中")

            # 状态指示器
            st.markdown("""
            <div style='
                display: flex;
                align-items: center;
                gap: 8px;
                margin-top: 8px;
            '>
                <div style='
                    width: 8px;
                    height: 8px;
                    border-radius: 50%;
                    background: #10B981;
                    animation: pulse 2s infinite;
                '></div>
                <span style='color: #64748B; font-size: 12px;'>正常运行</span>
            </div>
            """, unsafe_allow_html=True)

    with enabled_col2:
        st.button("🔄 禁用", key="disable_btn", use_container_width=True)

    with enabled_col3:
        st.button("⚙️ 配置", key="config_btn", use_container_width=True)

    st.divider()

    # 浏览连接器区域
    st.subheader("📂 浏览连接器")

    # 连接器网格布局
    conn_col1, conn_col2, conn_col3 = st.columns(3)

    # GitHub连接器
    with conn_col1:
        with st.container(border=True):
            st.markdown("""
            <div style='text-align: center; padding: 10px;'>
                <div style='
                    background: rgba(107, 114, 128, 0.1);
                    width: 60px;
                    height: 60px;
                    border-radius: 12px;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    margin: 0 auto 12px;
                    font-size: 24px;
                '>🐙</div>
                <h4 style='margin: 0; color: #1E293B;'>GitHub连接器</h4>
                <p style='color: #64748B; font-size: 14px; margin: 4px 0;'>代码仓库管理</p>
            </div>
            """, unsafe_allow_html=True)
            st.button("🔄 启用", key="enable_github", use_container_width=True)

    # Notion连接器
    with conn_col2:
        with st.container(border=True):
            st.markdown("""
            <div style='text-align: center; padding: 10px;'>
                <div style='
                    background: rgba(107, 114, 128, 0.1);
                    width: 60px;
                    height: 60px;
                    border-radius: 12px;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    margin: 0 auto 12px;
                    font-size: 24px;
                '>📝</div>
                <h4 style='margin: 0; color: #1E293B;'>Notion连接器</h4>
                <p style='color: #64748B; font-size: 14px; margin: 4px 0;'>文档协作工具</p>
            </div>
            """, unsafe_allow_html=True)
            st.button("🔄 启用", key="enable_notion", use_container_width=True)

    # Slack连接器
    with conn_col3:
        with st.container(border=True):
            st.markdown("""
            <div style='text-align: center; padding: 10px;'>
                <div style='
                    background: rgba(107, 114, 128, 0.1);
                    width: 60px;
                    height: 60px;
                    border-radius: 12px;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    margin: 0 auto 12px;
                    font-size: 24px;
                '>💬</div>
                <h4 style='margin: 0; color: #1E293B;'>Slack连接器</h4>
                <p style='color: #64748B; font-size: 14px; margin: 4px 0;'>团队沟通平台</p>
            </div>
            """, unsafe_allow_html=True)
            st.button("🔄 启用", key="enable_slack", use_container_width=True)

    st.divider()

    # 操作区域
    st.subheader("🔧 连接器操作")

    action_col1, action_col2, action_col3, action_col4 = st.columns(4)

    with action_col1:
        with st.container(border=True):
            st.markdown("<div style='text-align: center; font-size: 24px;'>➕</div>", unsafe_allow_html=True)
            st.markdown("<p style='text-align: center; margin: 0; font-weight: 500;'>添加连接器</p>",
                        unsafe_allow_html=True)
            st.button("点击添加", key="add_conn", use_container_width=True)

    with action_col2:
        with st.container(border=True):
            st.markdown("<div style='text-align: center; font-size: 24px;'>🔄</div>", unsafe_allow_html=True)
            st.markdown("<p style='text-align: center; margin: 0; font-weight: 500;'>刷新列表</p>",
                        unsafe_allow_html=True)
            st.button("点击刷新", key="refresh_list", use_container_width=True)

    with action_col3:
        with st.container(border=True):
            st.markdown("<div style='text-align: center; font-size: 24px;'>⚙️</div>", unsafe_allow_html=True)
            st.markdown("<p style='text-align: center; margin: 0; font-weight: 500;'>全局设置</p>",
                        unsafe_allow_html=True)
            st.button("点击配置", key="global_config", use_container_width=True)

    with action_col4:
        with st.container(border=True):
            st.markdown("<div style='text-align: center; font-size: 24px;'>📊</div>", unsafe_allow_html=True)
            st.markdown("<p style='text-align: center; margin: 0; font-weight: 500;'>使用统计</p>",
                        unsafe_allow_html=True)
            st.button("查看统计", key="view_stats", use_container_width=True)

    # 使用说明
    with st.expander("📚 使用说明", expanded=False):
        st.markdown("""
        ### 连接器管理指南

        **已启用连接器**
        - 显示当前正在运行的连接器
        - 支持实时状态监控
        - 可快速禁用或重新配置

        **浏览连接器**
        - 发现可用的连接器类型
        - 一键启用所需服务
        - 支持多种传输协议

        **操作说明**
        - 添加连接器：配置新的服务连接
        - 刷新列表：获取最新的连接器信息
        - 全局设置：配置系统级参数
        - 使用统计：查看连接器运行状态
        """)


# 在Streamlit应用中调用
if __name__ == "__main__":
    st.set_page_config(page_title="MCP管理", layout="wide")
    mcp_page()