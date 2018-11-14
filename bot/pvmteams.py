import asyncio
import traceback

import discord

from .cogs.utils import has_role, separator
from .cogs.models import Session, Team, BotMessage, Player


async def team_maker(client):
    session = Session()
    while True:
        running_teams = session.query(Team).filter_by(active=True)
        if running_teams:
            pass
        else:
            continue
        try:
            for team in running_teams:
                team_channel = client.get_channel(team.team_channel_id)
                invite_channel = client.get_channel(team.invite_channel_id)
                team_message = await team_channel.get_message(team.team_message_id)
                invite_message = await invite_channel.get_message(team.invite_message_id)

                async for message in invite_channel.history(after=invite_message):
                    sent_message = None
                    current_players = session.query(Player).filter_by(team=team.id)
                    # Validate Team Additions
                    if message.content.lower() == f'in {team.id}':
                        await message.delete()
                        if message.author.bot:
                            continue
                        if has_role(message.author, int(team.role)) or team.role is None:
                            if message.author.id not in current_players:
                                if current_players.count() < team.size:
                                    added_player = Player(player_id=message.author.id, team=team.id)
                                    session.add(added_player)
                                    sent_message = await invite_channel.send(
                                        f"{message.author.mention} foi adicionado ao time '{team.title}' "
                                        f"({current_players.count() + 1}/{team.size})\n"
                                        f"*(`in {team.id}`)*"
                                    )
                                else:
                                    sent_message = await invite_channel.send(
                                        f"{message.author.mention}, o time '{team.title}' já está cheio. "
                                        f"({current_players.count()}/{team.size})\n"
                                        f"*(`in {team.id}`)*"
                                    )
                            else:
                                sent_message = await invite_channel.send(
                                    f"{message.author.mention} já está no time '{team.title}'. "
                                    f"({current_players.count()}/{team.size})\n"
                                    f"*(`in {team.id}`)*"
                                )
                        else:
                            no_perm_embed = discord.Embed(
                                title=f"__Permissões insuficientes__",
                                description=f"{message.author.mention}, você precisa ter o cargo <@&{team.role}> "
                                            f"para entrar no Time '{team.title}' "
                                            f"({current_players.count()}/{team.size})\n"
                                            f"(*`in {team.id}`*)",
                                color=discord.Color.dark_red()
                            )
                            sent_message = await invite_channel.send(embed=no_perm_embed)
                    # Validate Team Opt-outs
                    elif message.content.lower() == f'out {team.id}':
                        await message.delete()
                        if message.author.bot:
                            continue
                        if message.author.id in current_players:
                            session.query(Player).filter_by(player_id=message.author.id, team=team.id).delete()
                            sent_message = await invite_channel.send(
                                f"{message.author.mention} foi removido do time '{team.title}' "
                                f"({current_players.count() - 1}/{team.size})\n"
                                f"*(`in {team.id}`)*"
                            )
                        else:
                            sent_message = await invite_channel.send(
                                f"{message.author.mention} já não estava no time '{team.title}'. "
                                f"({current_players.count()}/{team.size})\n"
                                f"*(`in {team.id}`)*"
                            )
                    if sent_message:
                        message = BotMessage(message_id=sent_message.id, team=team.id)
                        session.add(message)
                        session.commit()
                        embed_description = (
                            f"Marque presença no <#{team.invite_channel_id}>\n"
                            f"Criador: <@{team.author_id}>")
                        if team.role:
                            embed_description = (
                                f"Requisito: <@&{team.role}>\n"
                                f"{embed_description}")
                        team_embed = discord.Embed(
                            title=f"__{team.title}__ - {current_players.count()}/{team.size}",
                            description=embed_description,
                            color=discord.Color.purple()
                        )
                        footer = (f"Digite '{client.setting.prefix}del {team.id}' "
                                  f"para excluir o time. (Criador do time ou Mod/Mod+/Admin)")
                        team_embed.set_footer(
                            text=footer
                        )
                        players = session.query(Player).filter_by(team=team.id)
                        index = 0
                        if players:
                            for player in players:
                                team_embed.add_field(
                                    name=separator,
                                    value=f"{index + 1}- <@{player.player_id}>",
                                    inline=False
                                )
                                index += 1
                        try:
                            await team_message.edit(embed=team_embed)
                        except discord.errors.NotFound:
                            team.active = False
                            session.commit()
        except Exception as e:
            tb = traceback.format_exc()
            await client.send_logs(e, tb)
        await asyncio.sleep(2)