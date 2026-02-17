import dash
from dash import dcc, html, dash_table
from dash.dependencies import Input, Output
import dash_bootstrap_components as dbc
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import timedelta, datetime
import traceback
import plotly.express as px

Graph_template = "seaborn"  # "plotly_dark"


# =====================================================
# INITIAL DATA
# =====================================================

# Load transactions from CSV
def load_transactions_from_csv(file_path):
    df = pd.read_csv(file_path)
    transactions = df.to_dict(orient='records')  # Convert DataFrame to list of dictionaries
    return transactions


# Example usage
file_path = 'initial_transactions.csv'  # Adjust this path
initial_transactions = load_transactions_from_csv(file_path)

# FX column mapping
fx_col_map = {"EUR": "EURCZK=X", "USD": "USDCZK=X"}


# =====================================================
# HELPER FUNCTION FOR COLORS
# =====================================================

def get_ticker_colors(tickers):
    """Generate consistent colors for tickers using Plotly's qualitative color sequence"""
    colors = px.colors.qualitative.Plotly
    # If we have more tickers than colors, cycle through them
    return {ticker: colors[i % len(colors)] for i, ticker in enumerate(tickers)}


# =====================================================
# DATA PROCESSING FUNCTIONS
# =====================================================

def process_transactions(tx_data):
    """Convert transaction data to DataFrame and process dates"""
    tx = pd.DataFrame(tx_data)
    tx["time"] = pd.to_datetime(tx["time"])
    tx["date"] = tx["time"].dt.normalize()
    return tx


def get_fx_rates():
    """Download current FX rates"""
    try:
        fx = yf.download(
            ["EURUSD=X", "EURCZK=X", "USDCZK=X"],
            period="1d",
            progress=False,
            auto_adjust=True
        )["Close"]

        EURUSD = fx["EURUSD=X"].iloc[0] if not fx.empty else print("ERROR Forex EURUSD")
        EURCZK = fx["EURCZK=X"].iloc[-1] if not fx.empty else print("ERROR Forex EURCZK")
        USDCZK = fx["USDCZK=X"].iloc[-1] if not fx.empty else print("ERROR Forex USDCZK")
    except:
        # Fallback rates if download fails
        print("ERROR Forex rate find failed BEWARE")
        EURUSD = 1.05
        EURCZK = 24.5
        USDCZK = 23.0

    return {"EURUSD": EURUSD, "EURCZK": EURCZK, "USDCZK": USDCZK}


def download_price_data(tickers, start_date):
    """Download price data for all tickers"""
    if not tickers:
        return pd.DataFrame()

    try:
        prices = yf.download(
            tickers,
            start=start_date,
            progress=False,
            auto_adjust=True
        )

        # Check if we have the expected columns
        if "Open" in prices.columns and "Close" in prices.columns:
            return prices[["Open", "Close"]].ffill()
        elif isinstance(prices.columns, pd.MultiIndex):
            # Handle multi-index case
            return prices.xs("Close", axis=1, level=1).ffill()
        else:
            return pd.DataFrame()
    except:
        return pd.DataFrame()


def download_historical_fx(start_date):
    """Download historical FX rates"""
    try:
        fx_hist = yf.download(
            ["EURCZK=X", "USDCZK=X"],
            start=start_date,
            end=datetime.now(),
            progress=False,
            auto_adjust=True
        )["Close"].ffill()
        return fx_hist
    except:
        return pd.DataFrame()


def build_positions(tx, index):
    """Build cumulative positions over time"""
    positions = pd.DataFrame(0.0, index=index, columns=tx["ticker"].unique())
    for _, row in tx.iterrows():
        positions.loc[positions.index >= row["date"], row["ticker"]] += row["shares"]
    return positions


def portfolio_value_czk(prices, positions, tx, fx_rates):
    """Calculate portfolio value in CZK"""
    values = pd.DataFrame(index=prices.index)
    for ticker in positions.columns:
        currency = tx[tx["ticker"] == ticker]["currency"].iloc[0]
        fx = fx_rates["USDCZK"] if currency == "USD" else fx_rates["EURCZK"]
        if ticker in prices.columns.get_level_values(1):
            values[ticker] = prices["Close"][ticker] * positions[ticker] * fx
    values["TOTAL"] = values.sum(axis=1)
    return values


def current_portfolio_snapshot(prices, positions, tx, fx_rates):
    """Get current portfolio snapshot"""
    latest_date = prices.index[-1]
    rows = []
    for ticker in positions.columns:
        shares = positions.loc[latest_date, ticker]
        if shares == 0:
            continue
        currency = tx[tx["ticker"] == ticker]["currency"].iloc[0]
        fx = fx_rates["USDCZK"] if currency == "USD" else fx_rates["EURCZK"]
        if ticker in prices.columns.get_level_values(1):
            price = prices["Close"][ticker].iloc[-1]
            rows.append({
                "Ticker": ticker,
                "Shares": shares,
                "Price": price,
                "Currency": currency,
                "Total CZK": price * shares * fx
            })
    df = pd.DataFrame(rows)
    if not df.empty:
        df["Allocation %"] = df["Total CZK"] / df["Total CZK"].sum() * 100
    return df


def invested_capital(tx, prices, fx_rates):
    """Calculate invested capital using current FX rates"""
    invested_rows = []
    for _, row in tx.iterrows():
        ticker = row["ticker"]
        shares = row["shares"]
        currency = row["currency"]
        date = row["date"]

        if ticker not in prices.columns.get_level_values(1):
            continue

        try:
            price = prices.loc[date, ("Open", ticker)]
            fx = fx_rates["USDCZK"] if currency == "USD" else fx_rates["EURCZK"]
            invested_rows.append({
                "Ticker": ticker,
                "Shares": shares,
                "Buy Price": price,
                "Currency": currency,
                "Invested CZK": price * shares * fx
            })
        except:
            continue

    df = pd.DataFrame(invested_rows)
    if not df.empty:
        df_total = df.groupby("Ticker")["Invested CZK"].sum().reset_index()
        df_total["Total Invested CZK"] = df_total["Invested CZK"].sum()
        return df, df_total
    return pd.DataFrame(), pd.DataFrame()


def invested_capital_historical(tx, prices, fx_hist):
    """Calculate invested capital using historical FX rates"""
    invested_rows = []
    for _, row in tx.iterrows():
        ticker = row["ticker"]
        shares = row["shares"]
        currency = row["currency"]
        date = row["date"]

        if ticker not in prices.columns.get_level_values(1):
            continue

        try:
            price = prices.loc[date, ("Open", ticker)]
            fx_col = "USDCZK=X" if currency == "USD" else "EURCZK=X"
            fx = fx_hist.loc[date, fx_col]

            invested_rows.append({
                "Ticker": ticker,
                "Shares": shares,
                "Buy Price": price,
                "Currency": currency,
                "Invested CZK": price * shares * fx
            })
        except:
            continue

    df = pd.DataFrame(invested_rows)
    if not df.empty:
        df_total = df.groupby("Ticker")["Invested CZK"].sum().reset_index()
        df_total["Total Invested CZK"] = df_total["Invested CZK"].sum()
        return df, df_total
    return pd.DataFrame(), pd.DataFrame()


def build_allocation_percentage_history(prices, positions, tx, fx_hist):
    """Build historical allocation percentages"""
    allocation = pd.DataFrame(index=prices.index)

    for ticker in positions.columns:
        currency = tx[tx["ticker"] == ticker]["currency"].iloc[0]
        fx_col = fx_col_map[currency]

        if ticker in prices.columns.get_level_values(1) and fx_col in fx_hist.columns:
            allocation[ticker] = (
                    prices["Close"][ticker]
                    * positions[ticker]
                    * fx_hist[fx_col]
            )

    if allocation.empty:
        return pd.DataFrame()

    # total portfolio value
    total = allocation.sum(axis=1)

    # convert to percentage
    allocation_pct = allocation.div(total, axis=0) * 100

    # remove dates where portfolio is empty
    allocation_pct = allocation_pct[total > 0]

    return allocation_pct


def build_portfolio_value_and_pct(prices, positions, tx, fx_hist):
    """Build portfolio value and percentage history"""
    values = pd.DataFrame(index=prices.index)

    for ticker in positions.columns:
        currency = tx[tx["ticker"] == ticker]["currency"].iloc[0]
        fx_col = fx_col_map[currency]

        if ticker in prices.columns.get_level_values(1) and fx_col in fx_hist.columns:
            values[ticker] = (
                    prices["Close"][ticker]
                    * positions[ticker]
                    * fx_hist[fx_col]
            )

    if values.empty:
        return pd.DataFrame(), pd.DataFrame()

    values["TOTAL"] = values.sum(axis=1)

    # percentage allocation
    pct = values.div(values["TOTAL"], axis=0) * 100

    # remove empty portfolio days
    mask = values["TOTAL"] > 0
    return values[mask], pct[mask]


# =====================================================
# FUNCTION: ADD BUY MARKERS TO CHARTS
# =====================================================

def add_buy_markers_to_fig(fig, tx, prices, fx_hist, ticker_colors, y_func=None):
    """
    Add colored buy markers to a figure

    Parameters:
    - fig: plotly figure to add markers to
    - tx: transactions dataframe
    - prices: price data
    - fx_hist: historical fx rates
    - ticker_colors: dict mapping ticker to color
    - y_func: function to calculate y-value for marker (if None, uses buy_price * fx)
    """
    for _, row in tx.iterrows():
        if row["date"] in prices.index and row["ticker"] in prices.columns.get_level_values(1):
            try:
                buy_price = prices.loc[row["date"], ("Open", row["ticker"])]
                fx_col = "USDCZK=X" if row["currency"] == "USD" else "EURCZK=X"
                fx = fx_hist.loc[row["date"], fx_col]

                # Get color for this ticker
                color = ticker_colors.get(row["ticker"], "gray")

                # Calculate y-value (either custom or default)
                if y_func:
                    y_value = y_func(row, buy_price, fx)
                else:
                    y_value = buy_price * fx

                fig.add_trace(go.Scatter(
                    x=[row["time"]],
                    y=[y_value],
                    mode="markers",
                    marker=dict(
                        size=11,
                        symbol="triangle-up",
                        color=color,
                        line=dict(color="white", width=1)
                    ),
                    showlegend=False,
                    hovertemplate=(
                        f"<b>{row['ticker']}</b><br>"
                        f"Shares: {row['shares']}<br>"
                        f"Buy time: {row['time']}<br>"
                        f"Value: {buy_price * fx:,.0f} CZK<br>"
                        f"<extra></extra>"
                    )
                ))
            except Exception as e:
                continue

    return fig


# =====================================================
# NEW FUNCTION: PLOT FX RATES HISTORY
# =====================================================

def plot_fx_rates_history(fx_hist, resolution="D"):
    """Plot historical EUR/CZK and USD/CZK exchange rates"""
    if fx_hist.empty:
        fig = go.Figure()
        fig.update_layout(title="No FX data available", template=Graph_template)
        return fig

    # Resample if needed
    if resolution != "D":
        fx_hist_resampled = fx_hist.resample(resolution).last()
    else:
        fx_hist_resampled = fx_hist

    fig = go.Figure()

    # Add EUR/CZK trace
    if "EURCZK=X" in fx_hist_resampled.columns:
        fig.add_trace(go.Scatter(
            x=fx_hist_resampled.index,
            y=fx_hist_resampled["EURCZK=X"],
            mode="lines",
            name="EUR/CZK",
            line=dict(color="blue", width=2),
            hovertemplate=(
                "<b>EUR/CZK</b><br>"
                "Date: %{x|%Y-%m-%d}<br>"
                "Rate: %{y:.3f} CZK"
                "<extra></extra>"
            )
        ))

    # Add USD/CZK trace
    if "USDCZK=X" in fx_hist_resampled.columns:
        fig.add_trace(go.Scatter(
            x=fx_hist_resampled.index,
            y=fx_hist_resampled["USDCZK=X"],
            mode="lines",
            name="USD/CZK",
            line=dict(color="red", width=2),
            hovertemplate=(
                "<b>USD/CZK</b><br>"
                "Date: %{x|%Y-%m-%d}<br>"
                "Rate: %{y:.3f} CZK"
                "<extra></extra>"
            )
        ))

    # Add horizontal lines for current rates
    latest_eur = fx_hist["EURCZK=X"].iloc[-1] if "EURCZK=X" in fx_hist.columns else None
    latest_usd = fx_hist["USDCZK=X"].iloc[-1] if "USDCZK=X" in fx_hist.columns else None

    if latest_eur:
        fig.add_hline(
            y=latest_eur,
            line_dash="dash",
            line_color="blue",
            opacity=0.5,
            annotation_text=f"Current EUR/CZK: {latest_eur:.3f}",
            annotation_position="bottom right"
        )

    if latest_usd:
        fig.add_hline(
            y=latest_usd,
            line_dash="dash",
            line_color="red",
            opacity=0.5,
            annotation_text=f"Current USD/CZK: {latest_usd:.3f}",
            annotation_position="top right"
        )

    fig.update_layout(
        title="Historical Exchange Rates: EUR/CZK and USD/CZK",
        title_font_size=28,
        xaxis_title="Date",
        yaxis_title="Exchange Rate (CZK)",
        hovermode="x unified",
        xaxis=dict(
            rangeslider=dict(visible=True),
            rangeselector=dict(
                buttons=[
                    dict(count=1, label="1m", step="month", stepmode="backward"),
                    dict(count=3, label="3m", step="month", stepmode="backward"),
                    dict(count=6, label="6m", step="month", stepmode="backward"),
                    dict(count=1, label="1y", step="year", stepmode="backward"),
                    dict(count=3, label="3y", step="year", stepmode="backward"),
                    dict(count=5, label="5y", step="year", stepmode="backward"),
                    dict(step="all")
                ]
            )
        ),
        template=Graph_template
    )

    return fig


# =====================================================
# PLOTTING FUNCTIONS
# =====================================================

def plot_allocation_pie(snapshot_df):
    """Plot allocation pie chart"""
    if snapshot_df.empty:
        fig = go.Figure()
        fig.update_layout(
            title="No data available",
            template=Graph_template
        )
        return fig

    df_plot = snapshot_df.copy()
    df_plot["hover_text"] = df_plot.apply(
        lambda row: f"{row['Ticker']}<br>{row['Total CZK']:,.2f} CZK",
        axis=1
    )

    PieChartTotalCZK = round(df_plot["Total CZK"].sum(), 2)

    fig = go.Figure(data=[go.Pie(
        labels=df_plot["Ticker"],
        values=df_plot["Allocation %"],
        textinfo='label+percent',
        textfont_size=25,
        hovertemplate=(
            "<b>%{label}</b><br>"
            "%{customdata}<br>"
            "%{percent}"
            "<extra></extra>"
        ),
        customdata=df_plot["hover_text"]
    )])

    fig.update_layout(
        title_text=(
            "Portfolio Allocation (%) "
            f"{PieChartTotalCZK:,.2f} CZK   "
            f"{datetime.now().strftime('%d.%m.%Y %Hh-%Mm')}"
        ),
        title_font_size=28,
        template=Graph_template
    )
    return fig


def plot_portfolio_stocks_history(prices, positions, tx, fx_rates, fx_hist, ticker_colors, resolution="D"):
    """Plot historical value per asset with historical FX rates and colored buy markers"""
    history = pd.DataFrame(index=prices.index)

    for ticker in positions.columns:
        currency = tx[tx["ticker"] == ticker]["currency"].iloc[0]
        fx_col = "USDCZK=X" if currency == "USD" else "EURCZK=X"

        if ticker in prices.columns.get_level_values(1) and fx_col in fx_hist.columns:
            history[ticker] = prices["Close"][ticker] * positions[ticker] * fx_hist[fx_col]

    if history.empty:
        fig = go.Figure()
        fig.update_layout(title="No historical data available", template=Graph_template)
        return fig

    history["TOTAL"] = history.sum(axis=1)

    if resolution != "D":
        history = history.resample(resolution).last()

    fig = go.Figure()

    for ticker in positions.columns:
        if ticker in history.columns:
            color = ticker_colors.get(ticker, None)
            fig.add_trace(go.Scatter(
                x=history.index,
                y=history[ticker],
                mode="lines",
                name=ticker,
                line=dict(color=color, width=2),
                hovertemplate=(
                    "<b>%{fullData.name}</b><br>"
                    "Date: %{x|%Y-%m-%d}<br>"
                    "Value: %{y:,.0f} CZK"
                    "<extra></extra>"
                )
            ))

    fig.add_trace(go.Scatter(
        x=history.index,
        y=history["TOTAL"],
        mode="lines",
        name="PORTFOLIO TOTAL",
        line=dict(color="black", width=4),
        visible="legendonly",
        hovertemplate=(
            "<b>PORTFOLIO TOTAL</b><br>"
            "Date: %{x|%Y-%m-%d}<br>"
            "Value: %{y:,.0f} CZK"
            "<extra></extra>"
        )
    ))

    # Add colored buy markers
    fig = add_buy_markers_to_fig(fig, tx, prices, fx_hist, ticker_colors)

    fig.update_layout(
        title="Historical Value per Asset (CZK)",
        title_font_size=28,
        xaxis_title="Date",
        yaxis_title="Value (CZK)",
        xaxis=dict(
            rangeslider=dict(visible=True),
            rangeselector=dict(
                buttons=[
                    dict(count=1, label="1m", step="month", stepmode="backward"),
                    dict(count=3, label="3m", step="month", stepmode="backward"),
                    dict(count=6, label="6m", step="month", stepmode="backward"),
                    dict(count=1, label="1y", step="year", stepmode="backward"),
                    dict(step="all")
                ]
            )
        ),
        template=Graph_template
    )
    return fig


def plot_profit_loss_over_time(prices, positions, tx, fx_rates, fx_hist, ticker_colors):
    """Plot profit/loss over time using historical FX with colored buy markers"""
    history = pd.DataFrame(index=prices.index)

    for ticker in positions.columns:
        currency = tx[tx["ticker"] == ticker]["currency"].iloc[0]
        fx_col = "USDCZK=X" if currency == "USD" else "EURCZK=X"

        if ticker in prices.columns.get_level_values(1) and fx_col in fx_hist.columns:
            history[ticker] = prices["Close"][ticker] * positions[ticker] * fx_hist[fx_col]

    if history.empty:
        fig = go.Figure()
        fig.update_layout(title="No data available", template=Graph_template)
        return fig

    history["TOTAL"] = history.sum(axis=1)

    invested_cumsum = pd.Series(0.0, index=history.index)
    for _, row in tx.iterrows():
        ticker = row["ticker"]
        currency = row["currency"]
        date = row["date"]

        if ticker in prices.columns.get_level_values(1):
            try:
                fx_col = "USDCZK=X" if currency == "USD" else "EURCZK=X"
                fx = fx_hist.loc[date, fx_col]
                price = prices.loc[date, ("Open", ticker)]
                invested_cumsum.loc[invested_cumsum.index >= date] += row["shares"] * price * fx
            except:
                continue

    pl = history["TOTAL"] - invested_cumsum

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=history.index, y=history["TOTAL"], name="Portfolio Value (CZK)",
                             line=dict(color="black", width=3)))
    fig.add_trace(go.Scatter(x=invested_cumsum.index, y=invested_cumsum, name="Cumulative Invested (CZK)",
                             line=dict(color="blue", width=2, dash="dot")))
    fig.add_trace(go.Scatter(x=pl.index, y=pl, name="Profit / Loss (CZK)", line=dict(color="green", width=2)))

    # Add colored buy markers (use portfolio value for y-axis)
    def y_func(row, buy_price, fx):
        # We want markers on the profit/loss line, but that's tricky
        # Let's place them on the portfolio value line instead
        return buy_price * fx

    fig = add_buy_markers_to_fig(fig, tx, prices, fx_hist, ticker_colors, y_func)

    fig.update_layout(
        title="Portfolio Value vs Invested Capital vs Profit/Loss",
        xaxis_title="Date",
        yaxis_title="CZK",
        hovermode="x unified",
        template=Graph_template
    )
    return fig


def plot_allocation_treemap_with_growth(snapshot_df, invested_df):
    """Plot treemap with growth colors"""
    if snapshot_df.empty or invested_df.empty:
        fig = go.Figure()
        fig.update_layout(title="No data available", template=Graph_template)
        return fig

    invested_per_ticker = invested_df.groupby("Ticker")["Invested CZK"].sum().reset_index()
    df = snapshot_df.merge(invested_per_ticker, on="Ticker", how="left")
    df["Growth %"] = (df["Total CZK"] / df["Invested CZK"] - 1) * 100

    top_levels = ["EUR", "USD"]
    labels = []
    parents = []
    values = []
    customdata = []
    colors = []

    for ccy in top_levels:
        labels.append(ccy)
        parents.append("")
        values.append(0)
        customdata.append(0)
        colors.append(None)

    for _, row in df.iterrows():
        labels.append(row["Ticker"])
        parents.append(row["Currency"])
        values.append(row["Allocation %"])
        customdata.append([row["Total CZK"], row["Invested CZK"], row["Growth %"]])
        colors.append(row["Growth %"])

    colorscale = [
        [0.0, "red"],
        [0.5, "white"],
        [1.0, "green"]
    ]

    # Handle case where all growth values might be the same
    growth_min = df["Growth %"].min()
    growth_max = df["Growth %"].max()
    abs_max = max(abs(growth_min), abs(growth_max)) if not pd.isna(growth_min) else 1

    fig = go.Figure(go.Treemap(
        labels=labels,
        parents=parents,
        values=values,
        textinfo="label+value+percent entry",
        hovertemplate=(
            "<b>%{label}</b><br>"
            "Currency: %{parent}<br>"
            "Allocation: %{value:.2f}%<br>"
            "Current CZK: %{customdata[0]:,.2f}<br>"
            "Invested CZK: %{customdata[1]:,.2f}<br>"
            "Growth: %{customdata[2]:.2f}%<extra></extra>"
        ),
        customdata=customdata,
        marker=dict(
            colors=colors,
            colorscale=colorscale,
            cmin=-abs_max,
            cmax=abs_max,
            showscale=True,
            colorbar=dict(title="Growth %")
        )
    ))

    fig.update_layout(
        title="Portfolio Allocation Treemap by Currency with Growth",
        title_font_size=28,
        template=Graph_template
    )
    return fig


def plot_drawdown(prices, positions, tx, fx_rates, fx_hist, ticker_colors):
    """Plot drawdown chart using historical FX with colored buy markers"""
    values = pd.Series(0.0, index=prices.index)

    for ticker in positions.columns:
        currency = tx[tx["ticker"] == ticker]["currency"].iloc[0]
        fx_col = "USDCZK=X" if currency == "USD" else "EURCZK=X"

        if ticker in prices.columns.get_level_values(1) and fx_col in fx_hist.columns:
            values += prices["Close"][ticker] * positions[ticker] * fx_hist[fx_col]

    values = values[values > 0]

    if values.empty:
        fig = go.Figure()
        fig.update_layout(title="No data available", template=Graph_template)
        return fig

    running_max = values.cummax()
    drawdown = (values - running_max) / running_max * 100

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=drawdown.index,
        y=drawdown,
        fill="tozeroy",
        name="Drawdown (%)",
        hovertemplate=(
            "Date: %{x|%Y-%m-%d}<br>"
            "Drawdown: %{y:.2f}%"
            "<extra></extra>"
        )
    ))

    # Add colored buy markers (use drawdown value for y-axis)
    def y_func(row, buy_price, fx):
        # For drawdown chart, we need to find the drawdown at the buy date
        if row["date"] in drawdown.index:
            return drawdown.loc[row["date"]]
        return None

    # Filter out None values
    fig = add_buy_markers_to_fig(fig, tx, prices, fx_hist, ticker_colors, y_func)

    fig.update_layout(
        title=f"Portfolio Drawdown (%) - Max: {drawdown.min():.2f}%",
        xaxis_title="Date",
        yaxis_title="Drawdown %",
        hovermode="x unified",
        template=Graph_template
    )
    return fig


def plot_allocation_area_chart(allocation_pct, tx, prices, fx_hist, ticker_colors, resolution="W"):
    """Plot allocation area chart over time with colored buy markers"""
    if allocation_pct.empty:
        fig = go.Figure()
        fig.update_layout(title="No allocation data available", template=Graph_template)
        return fig

    if resolution != "D":
        allocation_pct = allocation_pct.resample(resolution).last()

    fig = go.Figure()

    for ticker in allocation_pct.columns:
        color = ticker_colors.get(ticker, None)
        fig.add_trace(go.Scatter(
            x=allocation_pct.index,
            y=allocation_pct[ticker],
            stackgroup="one",  # this makes it an area chart
            name=ticker,
            mode="lines",
            line=dict(color=color),
            hovertemplate=(
                "<b>%{fullData.name}</b><br>"
                "Date: %{x|%Y-%m-%d}<br>"
                "Allocation: %{y:.2f}%"
                "<extra></extra>"
            )
        ))

    # Add colored buy markers (use 0 for y-axis since it's percentage chart)
    def y_func(row, buy_price, fx):
        # For allocation chart, we want markers at the bottom
        # Let's put them at 0% with a custom hover
        return 0

    fig = add_buy_markers_to_fig(fig, tx, prices, fx_hist, ticker_colors, y_func)

    fig.update_layout(
        title="Portfolio Allocation Over Time (%)",
        xaxis_title="Date",
        yaxis_title="Portfolio Allocation (%)",
        hovermode="x unified",
        yaxis=dict(
            range=[0, 100],
            ticksuffix="%"
        ),
        xaxis=dict(
            rangeslider=dict(visible=True),
            rangeselector=dict(
                buttons=[
                    dict(count=1, label="1m", step="month", stepmode="backward"),
                    dict(count=3, label="3m", step="month", stepmode="backward"),
                    dict(count=6, label="6m", step="month", stepmode="backward"),
                    dict(count=1, label="1y", step="year", stepmode="backward"),
                    dict(step="all")
                ]
            )
        ),
        template=Graph_template
    )
    return fig


def plot_compound_growth_area(values, pct, tx, prices, fx_hist, ticker_colors, resolution="W"):
    """Plot compound growth area chart with colored buy markers"""
    if values.empty or pct.empty:
        fig = go.Figure()
        fig.update_layout(title="No growth data available", template=Graph_template)
        return fig

    if resolution != "D":
        values = values.resample(resolution).last()
        pct = pct.resample(resolution).last()

    fig = go.Figure()

    for ticker in values.columns.drop("TOTAL"):
        if ticker in values.columns and ticker in pct.columns:
            color = ticker_colors.get(ticker, None)
            fig.add_trace(go.Scatter(
                x=values.index,
                y=values[ticker],
                stackgroup="one",  # stacked CZK area
                name=ticker,
                mode="lines",
                line=dict(color=color),
                customdata=np.stack([
                    pct[ticker],
                    values["TOTAL"]
                ], axis=-1),
                hovertemplate=(
                    "<b>%{fullData.name}</b><br>"
                    "Date: %{x|%Y-%m-%d}<br>"
                    "Value: %{y:,.0f} CZK<br>"
                    "Allocation: %{customdata[0]:.2f}%<br>"
                    "<br><b>Total portfolio:</b><br>"
                    "%{customdata[1]:,.0f} CZK"
                    "<extra></extra>"
                )
            ))

    # Add colored buy markers
    fig = add_buy_markers_to_fig(fig, tx, prices, fx_hist, ticker_colors)

    fig.update_layout(
        title="Portfolio Compound Growth with Allocation Over Time",
        xaxis_title="Date",
        yaxis_title="Portfolio Value (CZK)",
        hovermode="x unified",
        xaxis=dict(
            rangeslider=dict(visible=True),
            rangeselector=dict(
                buttons=[
                    dict(count=1, label="1m", step="month", stepmode="backward"),
                    dict(count=3, label="3m", step="month", stepmode="backward"),
                    dict(count=6, label="6m", step="month", stepmode="backward"),
                    dict(count=1, label="1y", step="year", stepmode="backward"),
                    dict(step="all")
                ]
            )
        ),
        template=Graph_template
    )
    return fig


# =====================================================
# DASH APP INITIALIZATION
# =====================================================

app = dash.Dash(
    __name__,
    external_stylesheets=[dbc.themes.MORPH],
    suppress_callback_exceptions=True
)

server = app.server

# =====================================================
# LAYOUT
# =====================================================

app.layout = dbc.Container(fluid=True, children=[

    # HEADER
    dbc.Row(
        dbc.Col(
            html.H1(f"FP Dashboard {datetime.now().strftime('%Y-%m-%d %H:%M')}", className="text-center my-4"),
            width=12
        )
    ),

    dbc.Row([

        # =============================================
        # SIDEBAR
        # =============================================
        dbc.Col(width=3, children=[

            dbc.Card([
                dbc.CardHeader("Controls", className="h5"),
                dbc.CardBody([

                    dbc.Label("Select Chart Type"),
                    dcc.Dropdown(
                        id="view_selector",
                        options=[
                            {"label": "Allocation Pie", "value": "pie"},
                            {"label": "Historical Stocks", "value": "history"},
                            {"label": "Profit/Loss Over Time", "value": "pl"},
                            {"label": "Treemap with Growth", "value": "treemap"},
                            {"label": "Drawdown", "value": "drawdown"},
                            {"label": "Allocation Over Time (%)", "value": "allocation_area"},
                            {"label": "Compound Growth Area", "value": "growth_area"},
                            {"label": "FX Rates (EUR/CZK & USD/CZK)", "value": "fx_rates"},
                        ],
                        value="pie",
                        clearable=False,
                        style={"color": "black"}
                    ),

                    html.Hr(),

                    dbc.Label("Resolution"),
                    dcc.Dropdown(
                        id="resolution_selector",
                        options=[
                            {"label": "Daily", "value": "D"},
                            {"label": "Weekly", "value": "W"},
                            {"label": "Monthly", "value": "M"},
                        ],
                        value="W",
                        clearable=False,
                        style={"color": "black"}
                    ),

                    html.Hr(),

                    dbc.Label("📝 Transactions"),
                    html.P("Edit transactions below:", className="text-muted"),

                    dash_table.DataTable(
                        id="transaction_table",
                        columns=[
                            {"name": "Ticker", "id": "ticker", "editable": True},
                            {"name": "Shares", "id": "shares", "editable": True, "type": "numeric"},
                            {"name": "Currency", "id": "currency", "editable": True, "presentation": "dropdown"},
                            {"name": "Time", "id": "time", "editable": True},
                        ],
                        data=initial_transactions,
                        editable=True,
                        row_deletable=True,
                        style_table={"overflowX": "auto", "height": "400px", "overflowY": "auto"},
                        style_cell={
                            "backgroundColor": "#1e1e1e",
                            "color": "white",
                            "fontSize": "12px",
                            "textAlign": "left"
                        },
                        style_header={
                            "backgroundColor": "#333",
                            "color": "white",
                            "fontWeight": "bold"
                        },
                        dropdown={
                            "currency": {
                                "options": [
                                    {"label": "EUR", "value": "EUR"},
                                    {"label": "USD", "value": "USD"},
                                ]
                            }
                        }
                    ),

                    html.Br(),

                    dbc.Button("Add Row", id="add-row-button", color="secondary", size="sm"),

                    html.Hr(),

                    html.Div(id="summary-stats", className="mt-3")
                ])
            ])

        ]),

        # =============================================
        # MAIN GRAPH AREA
        # =============================================
        dbc.Col(width=9, children=[

            dbc.Card([
                dbc.CardBody([
                    dcc.Loading(
                        dcc.Graph(id="main_graph", style={"height": "70vh"}),
                        type="circle"
                    )
                ])
            ]),

            dbc.Row([
                dbc.Col([
                    dbc.Card([
                        dbc.CardBody([
                            html.H5("Current Portfolio Value", className="card-title"),
                            html.H2(id="current-value-display", children="0 CZK")
                        ])
                    ], color="primary", inverse=True)
                ], width=4),
                dbc.Col([
                    dbc.Card([
                        dbc.CardBody([
                            html.H5("Total Invested", className="card-title"),
                            html.H2(id="total-invested-display", children="0 CZK")
                        ])
                    ], color="info", inverse=True)
                ], width=4),
                dbc.Col([
                    dbc.Card([
                        dbc.CardBody([
                            html.H5("Profit/Loss", className="card-title"),
                            html.H2(id="pl-display", children="0 CZK")
                        ])
                    ], color="secondary", inverse=True, id="pl-card")
                ], width=4),
            ], className="mt-3")
        ])
    ])
])


# =====================================================
# CALLBACKS
# =====================================================

@app.callback(
    Output("transaction_table", "data"),
    Input("add-row-button", "n_clicks"),
    prevent_initial_call=True
)
def add_row(n_clicks):
    if n_clicks is None:
        return dash.no_update

    new_row = {
        "ticker": "NEW",
        "shares": 1.0,
        "currency": "EUR",
        "time": datetime.now().strftime("%Y-%m-%d %H:%M")
    }

    # Get current data and append
    current_data = initial_transactions.copy()
    current_data.append(new_row)
    return current_data


@app.callback(
    [Output("main_graph", "figure"),
     Output("current-value-display", "children"),
     Output("total-invested-display", "children"),
     Output("pl-display", "children"),
     Output("pl-card", "color")],
    [Input("transaction_table", "data"),
     Input("view_selector", "value"),
     Input("resolution_selector", "value")]
)
def update_dashboard(data, view, resolution):
    if not data or len(data) == 0:
        fig = go.Figure()
        fig.update_layout(title="No transaction data", template=Graph_template)
        return fig, "0 CZK", "0 CZK", "0 CZK", "secondary"

    try:
        # Process transactions
        tx = process_transactions(data)

        # Get data
        first_buy_date = tx["date"].min()
        start_date = first_buy_date - timedelta(days=1)

        fx_rates = get_fx_rates()
        fx_hist = download_historical_fx(start_date)

        tickers = tx["ticker"].unique().tolist()
        prices = download_price_data(tickers, start_date)

        if prices.empty:
            fig = go.Figure()
            fig.update_layout(title="No price data available", template=Graph_template)
            return fig, "0 CZK", "0 CZK", "0 CZK", "secondary"

        # Filter to valid tickers
        valid_tickers = []
        for t in tickers:
            if t in prices.columns.get_level_values(1):
                valid_tickers.append(t)

        tx_valid = tx[tx["ticker"].isin(valid_tickers)]

        if tx_valid.empty:
            fig = go.Figure()
            fig.update_layout(title="No valid tickers with data", template=Graph_template)
            return fig, "0 CZK", "0 CZK", "0 CZK", "secondary"

        # Generate consistent colors for tickers
        ticker_colors = get_ticker_colors(valid_tickers)

        positions = build_positions(tx_valid, prices.index)

        # SPECIAL CASE: FX Rates graph doesn't need portfolio data
        if view == "fx_rates":
            fig = plot_fx_rates_history(fx_hist, resolution)
            # Still calculate portfolio stats for the summary cards
            invested_df, invested_total = invested_capital_historical(tx_valid, prices, fx_hist)

            # Calculate current value with historical FX
            current_value = 0
            for ticker in positions.columns:
                currency = tx_valid[tx_valid["ticker"] == ticker]["currency"].iloc[0]
                fx_col = "USDCZK=X" if currency == "USD" else "EURCZK=X"
                shares = positions.iloc[-1][ticker]
                if shares > 0 and ticker in prices.columns.get_level_values(1) and fx_col in fx_hist.columns:
                    price = prices["Close"][ticker].iloc[-1]
                    fx = fx_hist[fx_col].iloc[-1]
                    current_value += price * shares * fx

            total_invested = invested_total["Total Invested CZK"].iloc[0] if not invested_total.empty else 0
            pl_value = current_value - total_invested
            pl_color = "success" if pl_value >= 0 else "danger"
            pl_pct = (pl_value / total_invested * 100) if total_invested > 0 else 0

            return (
                fig,
                f"{current_value:,.0f} CZK",
                f"{total_invested:,.0f} CZK",
                f"{pl_value:,.0f} CZK ({pl_pct:.1f}%)" if total_invested > 0 else "0 CZK",
                pl_color
            )

        # Calculate different metrics based on view for other graph types
        if view in ["history", "pl", "drawdown", "allocation_area", "growth_area"]:
            # Use historical FX for accuracy
            invested_df, invested_total = invested_capital_historical(tx_valid, prices, fx_hist)

            # Calculate current value with historical FX
            current_value = 0
            for ticker in positions.columns:
                currency = tx_valid[tx_valid["ticker"] == ticker]["currency"].iloc[0]
                fx_col = "USDCZK=X" if currency == "USD" else "EURCZK=X"
                shares = positions.iloc[-1][ticker]
                if shares > 0 and ticker in prices.columns.get_level_values(1) and fx_col in fx_hist.columns:
                    price = prices["Close"][ticker].iloc[-1]
                    fx = fx_hist[fx_col].iloc[-1]
                    current_value += price * shares * fx
        else:
            # Use current FX for snapshot views
            snapshot_df = current_portfolio_snapshot(prices, positions, tx_valid, fx_rates)
            invested_df, invested_total = invested_capital(tx_valid, prices, fx_rates)
            current_value = snapshot_df["Total CZK"].sum() if not snapshot_df.empty else 0

        total_invested = invested_total["Total Invested CZK"].iloc[0] if not invested_total.empty else 0
        pl_value = current_value - total_invested
        pl_color = "success" if pl_value >= 0 else "danger"
        pl_pct = (pl_value / total_invested * 100) if total_invested > 0 else 0

        # Generate figure based on view with colored buy markers
        if view == "pie":
            snapshot_df = current_portfolio_snapshot(prices, positions, tx_valid, fx_rates)
            fig = plot_allocation_pie(snapshot_df)
        elif view == "history":
            fig = plot_portfolio_stocks_history(prices, positions, tx_valid, fx_rates, fx_hist, ticker_colors,
                                                resolution)
        elif view == "pl":
            fig = plot_profit_loss_over_time(prices, positions, tx_valid, fx_rates, fx_hist, ticker_colors)
        elif view == "treemap":
            snapshot_df = current_portfolio_snapshot(prices, positions, tx_valid, fx_rates)
            fig = plot_allocation_treemap_with_growth(snapshot_df, invested_df)
        elif view == "drawdown":
            fig = plot_drawdown(prices, positions, tx_valid, fx_rates, fx_hist, ticker_colors)
        elif view == "allocation_area":
            allocation_pct = build_allocation_percentage_history(prices, positions, tx_valid, fx_hist)
            fig = plot_allocation_area_chart(allocation_pct, tx_valid, prices, fx_hist, ticker_colors, resolution)
        elif view == "growth_area":
            values, pct = build_portfolio_value_and_pct(prices, positions, tx_valid, fx_hist)
            fig = plot_compound_growth_area(values, pct, tx_valid, prices, fx_hist, ticker_colors, resolution)
        else:
            # Default to pie chart
            snapshot_df = current_portfolio_snapshot(prices, positions, tx_valid, fx_rates)
            fig = plot_allocation_pie(snapshot_df)

        return (
            fig,
            f"{current_value:,.0f} CZK",
            f"{total_invested:,.0f} CZK",
            f"{pl_value:,.0f} CZK ({pl_pct:.1f}%)" if total_invested > 0 else "0 CZK",
            pl_color
        )

    except Exception as e:
        print(f"Error: {e}")
        traceback.print_exc()
        fig = go.Figure()
        fig.update_layout(title=f"Error: {str(e)}", template=Graph_template)
        return fig, "Error", "Error", "Error", "secondary"


# =====================================================
# RUN APP
# =====================================================

if __name__ == "__main__":
    app.run(debug=True)
