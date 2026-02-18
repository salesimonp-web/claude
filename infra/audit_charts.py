#!/usr/bin/env python3
"""Generate audit charts for EC2 infrastructure review."""
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
import os

output_dir = os.path.dirname(os.path.abspath(__file__))

# Style global
plt.rcParams.update({
    'figure.facecolor': '#1a1a2e',
    'axes.facecolor': '#16213e',
    'text.color': '#e0e0e0',
    'axes.labelcolor': '#e0e0e0',
    'xtick.color': '#e0e0e0',
    'ytick.color': '#e0e0e0',
    'axes.edgecolor': '#333366',
    'grid.color': '#333366',
    'font.size': 11,
    'font.family': 'sans-serif',
})

COLORS = ['#00d2ff', '#7b2ff7', '#ff6b6b', '#ffd93d', '#6bcb77', '#4d96ff', '#ff922b', '#e64980']

# ═══════════════════════════════════════════════════════
# CHART 1: RAM Usage Breakdown
# ═══════════════════════════════════════════════════════
fig, ax = plt.subplots(figsize=(10, 6))

services = ['OpenClaw\nGateway', 'Claude Code\nDaemon', 'NordVPN\nDaemon', 'Trading Bot\n(bot.py)', 'Airdrop\nFarmer', 'Tailscale', 'Système\n& Autres', 'LIBRE']
ram_mb = [359, 225, 88, 68, 60, 40, 360, 6554]  # Total ~7754 MB = 7.6 GiB

colors_ram = COLORS[:7] + ['#2d4a22']
explode = [0.02]*7 + [0.05]

wedges, texts, autotexts = ax.pie(ram_mb, labels=services, autopct=lambda p: f'{p:.1f}%' if p > 3 else '',
                                    colors=colors_ram, explode=explode, startangle=90,
                                    textprops={'fontsize': 9}, pctdistance=0.8)
for t in autotexts:
    t.set_fontsize(8)
    t.set_color('white')

ax.set_title('Répartition RAM EC2 (m7i-flex.large — 7.6 GiB)', fontsize=14, fontweight='bold', pad=20)

# Legend with MB values
legend_labels = [f'{s.replace(chr(10), " ")} — {m} MB' for s, m in zip(services, ram_mb)]
ax.legend(legend_labels, loc='center left', bbox_to_anchor=(-0.35, 0.5), fontsize=8, framealpha=0.3)

plt.tight_layout()
plt.savefig(os.path.join(output_dir, 'audit_1_ram.png'), dpi=150, bbox_inches='tight')
plt.close()

# ═══════════════════════════════════════════════════════
# CHART 2: Cost Comparison — AWS vs Hostinger
# ═══════════════════════════════════════════════════════
fig, ax = plt.subplots(figsize=(12, 6))

categories = ['EC2\nm7i-flex.large', 'EC2 EBS\n48GB gp3', 'EC2 Data\nTransfer', 'EC2 n8n\n(2ème inst.)', 'TOTAL\nAWS/mois']
aws_costs = [36.3, 3.84, 3.0, 22.0, 65.14]

hostinger_categories = ['KVM2\n2vCPU/8GB', 'Inclus\n100GB SSD', 'Inclus\n8TB traffic', 'n8n sur\nmême VPS', 'TOTAL\nHostinger/mois']
hostinger_costs = [10.99, 0, 0, 0, 10.99]

x = np.arange(len(categories))
width = 0.35

bars1 = ax.bar(x - width/2, aws_costs, width, label='AWS (estimé)', color='#ff6b6b', alpha=0.9, edgecolor='white', linewidth=0.5)
bars2 = ax.bar(x + width/2, hostinger_costs, width, label='Hostinger KVM2', color='#6bcb77', alpha=0.9, edgecolor='white', linewidth=0.5)

for bar, val in zip(bars1, aws_costs):
    if val > 0:
        ax.text(bar.get_x() + bar.get_width()/2., bar.get_height() + 0.5, f'${val:.2f}', ha='center', va='bottom', fontsize=9, fontweight='bold')

for bar, val in zip(bars2, hostinger_costs):
    if val > 0:
        ax.text(bar.get_x() + bar.get_width()/2., bar.get_height() + 0.5, f'${val:.2f}', ha='center', va='bottom', fontsize=9, fontweight='bold')

ax.set_ylabel('Coût mensuel ($)')
ax.set_title('Comparaison Coûts Mensuels : AWS EC2 vs Hostinger KVM2', fontsize=14, fontweight='bold')
ax.set_xticks(x)
ax.set_xticklabels(categories, fontsize=9)
ax.legend(fontsize=11)
ax.set_ylim(0, 75)
ax.grid(axis='y', alpha=0.3)

# Savings annotation
ax.annotate(f'Économie: ${65.14-10.99:.2f}/mois\n= ${(65.14-10.99)*12:.0f}/an',
            xy=(4 + width/2, 10.99), xytext=(3.2, 50),
            arrowprops=dict(arrowstyle='->', color='#ffd93d', lw=2),
            fontsize=12, fontweight='bold', color='#ffd93d',
            bbox=dict(boxstyle='round,pad=0.5', facecolor='#1a1a2e', edgecolor='#ffd93d', alpha=0.9))

plt.tight_layout()
plt.savefig(os.path.join(output_dir, 'audit_2_costs.png'), dpi=150, bbox_inches='tight')
plt.close()

# ═══════════════════════════════════════════════════════
# CHART 3: AWS Credits Burn Rate + Projection
# ═══════════════════════════════════════════════════════
fig, ax = plt.subplots(figsize=(12, 6))

days = np.arange(0, 91)  # 3 months
initial_credits = 135

# Scenario 1: Continue AWS only (EC2 x2)
burn_rate_aws = 65.14 / 30  # per day
credits_aws = initial_credits - days * burn_rate_aws

# Scenario 2: Migrate to Hostinger, keep AWS credits for Bedrock
burn_bedrock_light = 15 / 30  # ~$15/month Bedrock usage
credits_bedrock = initial_credits - days * burn_bedrock_light

# Scenario 3: No AWS usage (all migrated)
credits_saved = np.full_like(days, initial_credits, dtype=float)

ax.plot(days, np.maximum(credits_aws, 0), color='#ff6b6b', linewidth=2.5, label='Scénario A: Rester sur AWS EC2 ($65/mois)')
ax.plot(days, np.maximum(credits_bedrock, 0), color='#ffd93d', linewidth=2.5, label='Scénario B: Hostinger + Bedrock ($15/mois)')
ax.plot(days, credits_saved, color='#6bcb77', linewidth=2.5, linestyle='--', label='Scénario C: Tout migrer, garder crédits ($0/mois)')

# Mark depletion points
depletion_a = initial_credits / burn_rate_aws
depletion_b = initial_credits / burn_bedrock_light
ax.axvline(x=depletion_a, color='#ff6b6b', linestyle=':', alpha=0.5)
ax.axvline(x=depletion_b, color='#ffd93d', linestyle=':', alpha=0.5)

ax.annotate(f'Épuisé: {depletion_a:.0f}j\n(~{depletion_a/30:.1f} mois)', xy=(depletion_a, 0), xytext=(depletion_a+5, 30),
            arrowprops=dict(arrowstyle='->', color='#ff6b6b'), fontsize=9, color='#ff6b6b')
ax.annotate(f'Épuisé: {depletion_b:.0f}j\n(~{depletion_b/30:.1f} mois)', xy=(min(depletion_b, 90), credits_bedrock[min(int(depletion_b), 90)] if depletion_b < 90 else credits_bedrock[-1]),
            xytext=(70, 100), arrowprops=dict(arrowstyle='->', color='#ffd93d'), fontsize=9, color='#ffd93d')

ax.fill_between(days, np.maximum(credits_aws, 0), alpha=0.1, color='#ff6b6b')
ax.fill_between(days, np.maximum(credits_bedrock, 0), alpha=0.1, color='#ffd93d')

ax.set_xlabel('Jours à partir de maintenant')
ax.set_ylabel('Crédits AWS restants ($)')
ax.set_title('Projection des Crédits AWS ($135) — 3 Scénarios', fontsize=14, fontweight='bold')
ax.legend(fontsize=10, loc='upper right')
ax.grid(alpha=0.3)
ax.set_xlim(0, 90)
ax.set_ylim(0, 145)

# Today marker
ax.axvline(x=0, color='white', linewidth=1, alpha=0.5)
ax.text(1, 140, 'AUJOURD\'HUI', fontsize=8, color='white', alpha=0.7)

plt.tight_layout()
plt.savefig(os.path.join(output_dir, 'audit_3_credits.png'), dpi=150, bbox_inches='tight')
plt.close()

# ═══════════════════════════════════════════════════════
# CHART 4: Tool Stack Completeness (Radar)
# ═══════════════════════════════════════════════════════
fig, ax = plt.subplots(figsize=(10, 8), subplot_kw=dict(polar=True))

categories_radar = [
    'Runtime\n(Python/Node)', 'Trading SDK\n(Hyperliquid)', 'Data Analysis\n(pandas/numpy)',
    'Base de\nDonnées', 'Monitoring\n& Alertes', 'Sécurité\n(VPN/Firewall)',
    'CI/CD\n& Docker', 'ML/AI\nLibraries', 'Log\nManagement', 'Backup\n& Recovery'
]

# Current state (0-10 scale)
current = [9, 8, 3, 1, 6, 4, 1, 1, 3, 1]
# Target state
target = [10, 9, 8, 7, 9, 8, 6, 7, 7, 6]

N = len(categories_radar)
angles = np.linspace(0, 2 * np.pi, N, endpoint=False).tolist()
angles += angles[:1]
current += current[:1]
target += target[:1]

ax.plot(angles, target, 'o-', linewidth=2, color='#ffd93d', label='Cible optimale', alpha=0.8)
ax.fill(angles, target, alpha=0.1, color='#ffd93d')
ax.plot(angles, current, 'o-', linewidth=2, color='#00d2ff', label='État actuel', alpha=0.9)
ax.fill(angles, current, alpha=0.2, color='#00d2ff')

ax.set_xticks(angles[:-1])
ax.set_xticklabels(categories_radar, fontsize=8)
ax.set_ylim(0, 10)
ax.set_yticks([2, 4, 6, 8, 10])
ax.set_yticklabels(['2', '4', '6', '8', '10'], fontsize=7)
ax.set_title('Maturité de la Stack Technique (0-10)', fontsize=14, fontweight='bold', pad=30)
ax.legend(loc='lower right', bbox_to_anchor=(1.3, 0), fontsize=10)
ax.grid(alpha=0.3)

plt.tight_layout()
plt.savefig(os.path.join(output_dir, 'audit_4_stack.png'), dpi=150, bbox_inches='tight')
plt.close()

# ═══════════════════════════════════════════════════════
# CHART 5: Bedrock vs Claude Code Pricing
# ═══════════════════════════════════════════════════════
fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))

# Left: Price per 1M tokens (input)
models = ['Opus 4\n(Bedrock)', 'Sonnet 4.5\n(Bedrock)', 'Haiku 4.5\n(Bedrock)', 'Claude Code\n(Abo Max $100)']
input_prices = [15, 3, 0.80, 0]  # $ per 1M input tokens (Claude Code is subscription)
output_prices = [75, 15, 4, 0]

x = np.arange(len(models))
width = 0.35

bars_in = ax1.bar(x - width/2, input_prices, width, label='Input /1M tokens', color='#00d2ff', alpha=0.9)
bars_out = ax1.bar(x + width/2, output_prices, width, label='Output /1M tokens', color='#7b2ff7', alpha=0.9)

for bar, val in zip(bars_in, input_prices):
    if val > 0:
        ax1.text(bar.get_x() + bar.get_width()/2., bar.get_height() + 0.5, f'${val}', ha='center', va='bottom', fontsize=9, fontweight='bold')
for bar, val in zip(bars_out, output_prices):
    if val > 0:
        ax1.text(bar.get_x() + bar.get_width()/2., bar.get_height() + 1, f'${val}', ha='center', va='bottom', fontsize=9, fontweight='bold')

ax1.set_ylabel('Prix ($)')
ax1.set_title('Coût par 1M Tokens — Bedrock', fontsize=12, fontweight='bold')
ax1.set_xticks(x)
ax1.set_xticklabels(models, fontsize=9)
ax1.legend(fontsize=9)
ax1.grid(axis='y', alpha=0.3)
ax1.text(3, 35, 'Inclus dans\nl\'abonnement\n(flat rate)', ha='center', fontsize=9, color='#6bcb77', fontweight='bold')

# Right: Monthly cost simulation for bot
scenarios = ['Bot léger\n(~500K tok/j)', 'Bot moyen\n(~2M tok/j)', 'Bot intensif\n(~5M tok/j)']
# Using Haiku for bot decisions (cheapest)
haiku_monthly = [0.5*30*0.80/1000 + 0.15*30*4/1000, 2*30*0.80/1000 + 0.6*30*4/1000, 5*30*0.80/1000 + 1.5*30*4/1000]
sonnet_monthly = [0.5*30*3/1000 + 0.15*30*15/1000, 2*30*3/1000 + 0.6*30*15/1000, 5*30*3/1000 + 1.5*30*15/1000]

x2 = np.arange(len(scenarios))
bars_h = ax2.bar(x2 - width/2, haiku_monthly, width, label='Haiku 4.5', color='#6bcb77', alpha=0.9)
bars_s = ax2.bar(x2 + width/2, sonnet_monthly, width, label='Sonnet 4.5', color='#4d96ff', alpha=0.9)

for bar, val in zip(bars_h, haiku_monthly):
    ax2.text(bar.get_x() + bar.get_width()/2., bar.get_height() + 0.2, f'${val:.1f}', ha='center', va='bottom', fontsize=9, fontweight='bold')
for bar, val in zip(bars_s, sonnet_monthly):
    ax2.text(bar.get_x() + bar.get_width()/2., bar.get_height() + 0.2, f'${val:.1f}', ha='center', va='bottom', fontsize=9, fontweight='bold')

ax2.set_ylabel('Coût mensuel ($)')
ax2.set_title('Coût Bedrock Mensuel — Bot de Trading', fontsize=12, fontweight='bold')
ax2.set_xticks(x2)
ax2.set_xticklabels(scenarios, fontsize=9)
ax2.legend(fontsize=9)
ax2.grid(axis='y', alpha=0.3)

plt.tight_layout()
plt.savefig(os.path.join(output_dir, 'audit_5_bedrock.png'), dpi=150, bbox_inches='tight')
plt.close()

print("✓ 5 charts generated successfully")
