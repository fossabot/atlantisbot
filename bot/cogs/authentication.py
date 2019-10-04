from typing import Union, Dict
import traceback
import datetime
import logging
import json

from discord.ext import commands, tasks
import asyncio
import discord
import aiohttp
import re

from bot.bot_client import Bot
from bot.orm.models import User
from bot.cogs.rsworld import grab_world, get_world, random_world, filtered_worlds

logger_atl = logging.getLogger('atlantis')


async def get_user_data(username: str, cs: aiohttp.ClientSession) -> dict:
    url = "http://services.runescape.com/m=website-data/"
    player_url = url + "playerDetails.ws?names=%5B%22{}%22%5D&callback=jQuery000000000000000_0000000000&_=0"

    async with cs.get(player_url.format(username.replace(' ', '%20'))) as r:
        # Check clan of player
        content = await r.text()
        return parse_user(content)


def parse_user(content: str) -> Union[Dict[str, Union[str, int]], None]:
    parsed = re.search(r'{"isSuffix":.*,"name":.*,"title":.*}', content)
    if not parsed:
        logger_atl.error(f'Unparsed result returned for user, content: {content}')
        print(content)
        return None
    parsed = parsed.group()
    info_dict = json.loads(parsed)
    info_dict['is_suffix'] = info_dict.pop('isSuffix')

    return info_dict


def settings_embed(settings: dict):
    """
    Accepts a dict in the following format and returns a discord Embed accordingly:

    settings = {
        "f2p_worlds": bool,
        "legacy_worlds": bool,
        "language": "pt" | "en" | "fr" | "de"
    }
    """

    embed = discord.Embed(
        title="Configurações de Mundos",
        description=(
            "Olá, para eu poder saber que você é mesmo o jogador que diz ser, "
            "eu vou precisar que você troque para os Mundos do jogo que irei o mostrar, "
            "siga as instruções abaixo para poder ser autenticado e receber o cargo de `Membro` "
            "no Servidor do Atlantis."
        ),
        color=discord.Color.blue()
    )

    # yes = "✅"
    # no = "❌"
    language = {"pt": "Português-br", "en": "Inglês", "fr": "Francês", "de": "Alemão"}

    # embed.add_field(name=f"Mundos Grátis {yes if settings['f2p_worlds'] else no}", value=separator, inline=False)
    # embed.add_field(name=f"Mundos Legado {yes if settings['legacy_worlds'] else no}", value=separator, inline=False)
    embed.add_field(name="Linguagem", value=language[settings['language']], inline=False)
    embed.add_field(name="Mundos Restantes", value=settings['worlds_left'], inline=False)
    return embed


class UserAuthentication(commands.Cog):

    def __init__(self, bot: Bot):
        self.bot = bot
        self.debugging = False

        if self.bot.setting.mode == 'prod' or self.debugging:
            self.check_users.start()

    def cog_unload(self):
        if self.bot.setting.mode == 'prod' or self.debugging:
            self.check_users.cancel()

    @tasks.loop(hours=1)
    async def check_users(self):
        """
        Check users that have changed names or left the clan since last authentication
        """
        atlantis = self.bot.get_guild(self.bot.setting.server_id)
        membro = atlantis.get_role(self.bot.setting.role.get('membro'))
        convidado = atlantis.get_role(self.bot.setting.role.get('convidado'))
        auth_chat = self.bot.setting.chat.get('auth')
        auth_chat: discord.TextChannel = atlantis.get_channel(auth_chat)

        try:
            async with aiohttp.ClientSession() as cs:
                with self.bot.db_session() as session:
                    users = session.query(User).all()
                    for user in users:
                        await asyncio.sleep(2)
                        user_data = await get_user_data(user.ingame_name, cs)
                        if not user_data:
                            # Sometimes call to RS3's API fail and a 404 html page is returned instead (...?)
                            continue
                        if not self.debugging and user_data['clan'] == self.bot.setting.clan_name:
                            # Don't do anything if player in in clan
                            continue
                        now = datetime.datetime.utcnow()
                        member: discord.Member = atlantis.get_member(int(user.discord_id))
                        if not member:
                            # Exclude from DB if user left the discord
                            session.delete(user)
                            continue

                        if user.warning_date:
                            # Only remove role if warning message was send 7 days before this check
                            if (now - user.warning_date).days >= 7:
                                session.delete(user)
                                await member.remove_roles(membro)
                                await member.add_roles(convidado)
                                await member.send(
                                    f"Olá {member.mention}! Há 7 dias, você trocou de nome ou saiu do Atlantis. "
                                    f"Como, até o momento, você não voltou a se registrar como membro do clã "
                                    f"autenticado ao Discord, seu cargo de `Membro` foi removido.\n\n"
                                    f"Caso ainda seja membro da comunidade, **autentique-se novamente "
                                    f"já!** O cargo de `Membro` é essencial para uma ampla participação "
                                    f"nas atividades do Atlantis.\n\n"
                                    f"Para se autenticar novamente, utilize o comando **`!membro`** aqui!\n\n"
                                )
                                await auth_chat.send(
                                    f"Usuário {member} (id: {member.id}) teve a Tag de Membro removida, já que o prazo "
                                    f"de 7 dias para re-autenticação expirou."
                                )
                        else:
                            await member.send(
                                f"Olá {member.mention}!\n"
                                f"Parece que você trocou o seu nome no jogo ou saiu do Clã! Desse modo, "
                                f"seu cargo de `Membro` deverá ser re-avaliada.\n\n"
                                f"**Caso tenha apenas mudado de nome**, será necessário se autenticar novamente "
                                f"no Discord do clã para continuar a ter acesso aos canais e vantagens do cargo de "
                                f"`Membro`. Torna-se válido ressaltar que o cargo é de fundamental importância para "
                                f"participação em muitas atividades do Atlantis.\n\n"
                                f"A partir de agora, você tem até **7 dias para se autenticar novamente** e "
                                f"registrar-se como Membro do Atlantis! Após este período, o cargo de `Membro` será "
                                f"removido até atualização de seu status.\n\n"
                                f"Caso tenha deixado a comunidade, o cargo só poderá ser reavido mediante um eventual "
                                f"reingresso no clã.\n\n"
                                f"Para se autenticar novamente, utilize o comando **`!membro`** aqui!"
                            )
                            await auth_chat.send(
                                f"Warning de 7 dias para reautenticação enviada para Usuário "
                                f"`{member}` (id: {member.id}) "
                            )
                            user.warning_date = now
                            session.commit()
        except Exception as e:
            await asyncio.sleep(30)
            await self.bot.send_logs(e, traceback, more_info={user: str(user), member: str(member)})

    @staticmethod
    async def send_cooldown(ctx):
        await ctx.send("O seu próximo mundo será enviado em 3...", delete_after=1)
        await asyncio.sleep(1)
        await ctx.send("O seu próximo mundo será enviado em 2...", delete_after=1)
        await asyncio.sleep(1)
        await ctx.send("O seu próximo mundo será enviado em 1...", delete_after=1)
        await asyncio.sleep(1)

    @commands.has_permissions(manage_channels=True)
    @commands.command(aliases=['membros'])
    async def authenticated_users(self, ctx: commands.Context):
        nb_space = '\u200B'
        embed = discord.Embed(
            title="Membros Autenticados",
            description="Nome in-game | Nome Discord | ID Discord",
            color=discord.Color.green()
        )
        with self.bot.db_session() as session:
            text = ""
            found = False
            for user in session.query(User).all():
                found = True
                text += f"{user.ingame_name} | {user.discord_name} | {user.discord_id}\n"
            if not found:
                text = "Não há nenhum Membro Autenticado no momento"
            embed.add_field(name=nb_space, value=text)
        await ctx.author.send(embed=embed)

    @commands.dm_only()
    @commands.cooldown(60, 0, commands.BucketType.user)
    @commands.command(aliases=['role', 'membro'])
    async def aplicar_role(self, ctx: commands.Context):
        logger_atl.info(f'Autenticação iniciada: {ctx.author}')

        atlantis = self.bot.get_guild(self.bot.setting.server_id)
        member: discord.Member = atlantis.get_member(ctx.author.id)
        if not member:
            logger_atl.info(f'Não está no servidor: {ctx.author}')
            invite = "<https://discord.me/atlantis>"
            return await ctx.send(f"Você precisa estar no Discord do Atlantis para se autenticar {invite}")
        membro: discord.Role = atlantis.get_role(self.bot.setting.role.get('membro'))
        convidado: discord.Role = atlantis.get_role(self.bot.setting.role.get('convidado'))

        with self.bot.db_session() as session:
            user = session.query(User).filter_by(discord_id=str(ctx.author.id)).first()
            if user:
                for role in member.roles:
                    role: discord.Role
                    if role.id == membro.id:
                        logger_atl.info(f'Não é um convidado: {ctx.author}')
                        return await ctx.send("Fool! Você não é um Convidado! Não é necessário se autenticar.")
                async with aiohttp.ClientSession() as cs:
                    user_data = await get_user_data(user.ingame_name, cs)
                if not user_data:
                    logger_atl.info(f'Erro acessando API do RuneScape: {ctx.author}')
                    return await ctx.send(
                        "Houve um erro ao tentar acessar a API do RuneScape. "
                        "Tente novamente mais tarde."
                    )
                if user_data.get('clan') == self.bot.setting.clan_name:
                    await member.add_roles(membro)
                    await member.remove_roles(convidado)
                    logger_atl.info(f'Já está autenticado, corrigindo dados: {ctx.author}')
                    return await ctx.send(
                        "Você já está autenticado! Seus dados foram corrigidos. "
                        "Você agora é um Membro do clã autenticado no Discord."
                    )

        def check(message: discord.Message):
            return message.author == ctx.author

        await ctx.send(f"{ctx.author.mention}, por favor me diga o seu nome no jogo.")

        try:
            ingame_name = await self.bot.wait_for('message', timeout=180.0, check=check)
        except asyncio.TimeoutError:
            logger_atl.info(f'Autenticação cancelada por Timeout: {ctx.author}')
            return await ctx.send(f"{ctx.author.mention}, autenticação cancelada. Tempo Esgotado.")

        await ctx.trigger_typing()

        with open('bot/worlds.json') as f:
            worlds = json.load(f)
        async with aiohttp.ClientSession() as cs:
            user_data = await get_user_data(ingame_name.content, cs)
        if not user_data:
            logger_atl.info(f'Erro ao acessar API do RuneScape: {ctx.author} ({user_data})')
            return await ctx.send("Houve um erro ao tentar acessar a API do RuneScape. Tente novamente mais tarde.")

        if user_data.get('clan') != self.bot.setting.clan_name:
            logger_atl.info(f'Jogador não existe ou não é Membro: {ctx.author} ({user_data})')
            return await ctx.send(
                f"{ctx.author.mention}, o jogador '{user_data.get('name')}' "
                f"não existe ou não é um membro do Clã Atlantis."
            )

        player_world = await grab_world(user_data['name'], user_data['clan'])

        if player_world == 'Offline' or not player_world:
            logger_atl.info(f'Jogador offline: {ctx.author} ({user_data})')
            return await ctx.send(
                f"{ctx.author.mention}, autenticação Cancelada. Você precisa estar Online.\n"
                f"Verifique suas configurações de privacidade no jogo."
            )

        player_world = get_world(worlds, player_world)
        if not player_world:
            logger_atl.error(f'Player world is None: {ctx.author} ({user_data})')
            raise Exception(f"Player world is None.")

        settings = {
            "f2p_worlds": player_world['f2p'],
            "legacy_worlds": player_world['legacy'],
            "language": player_world['language'],
            "worlds_left": 4
        }

        def confirm_check(reaction, user):
            return user == ctx.author and str(reaction.emoji) == '✅'

        settings_message = await ctx.send(embed=settings_embed(settings))
        confirm_message = await ctx.send("Reaja nessa mensagem quando estiver pronto.")
        await confirm_message.add_reaction('✅')
        try:
            await self.bot.wait_for('reaction_add', timeout=30, check=confirm_check)
        except asyncio.TimeoutError:
            logger_atl.info(f'Autenticação cancelada por Timeout: {ctx.author} ({user_data})')
            return await ctx.send(f"{ctx.author.mention}, autenticação cancelada. Tempo Esgotado.")
        await confirm_message.delete()
        await self.send_cooldown(ctx)

        # Filter worlds based on user settings
        world_list = filtered_worlds(worlds, **settings)

        failed_tries = 0
        last_world = 0
        worlds_done = []
        while settings['worlds_left'] > 0:
            # Update settings message
            await settings_message.edit(embed=settings_embed(settings))

            while True:
                # Don't allow same world 2 times in a row
                world = random_world(world_list)
                if world == last_world:
                    continue
                break
            last_world = world

            message: discord.Message = await ctx.send(
                f"{ctx.author.mention}, troque para o **Mundo {world['world']}**. "
                f"Reaja na mensagem quando estiver nele."
            )
            await message.add_reaction('✅')
            try:
                await self.bot.wait_for('reaction_add', timeout=30, check=confirm_check)
                await ctx.trigger_typing()
            except asyncio.TimeoutError:
                return await ctx.send(f"{ctx.author.mention}, autenticação cancelada. Tempo Esgotado.")
            wait_message = await ctx.send("Aguarde um momento...")
            await asyncio.sleep(1)
            player_world = await grab_world(user_data['name'], user_data['clan'])
            if player_world == 'Offline':
                # Check again in 3 seconds in case player was offline
                # He might have a slow connection, or the clan's webpage
                # is taking a while to update
                await asyncio.sleep(3)
                player_world = await grab_world(user_data['name'], user_data['clan'])
            await wait_message.delete()

            if world['world'] == player_world:
                settings['worlds_left'] -= 1
                worlds_done.append(player_world)
                wl = settings['worlds_left']
                plural_1 = 'm' if wl > 1 else ''
                plural_2 = 's' if wl > 1 else ''
                second_part = f"Falta{plural_1} {settings['worlds_left']} mundo{plural_2}." if wl != 0 else ''

                await ctx.send(f"**Mundo {world['world']}** verificado com sucesso. {second_part}")
            else:
                failed_tries += 1
                await ctx.send(f"Mundo incorreto ({player_world}). Tente novamente.")
                if failed_tries == 5:
                    logger_atl.info(f'Autenticação cancelada. Muitas tentativas: {ctx.author} ({user_data}) {settings}')
                    return await ctx.send("Autenticação cancelada. Muitas tentativas incorretas.")
            await message.delete()
            if settings['worlds_left'] == 0:
                break
        logger_atl.info(f'Autenticação feita com sucesso, {ctx.author} ({user_data}) {settings}')
        await settings_message.delete()

        await member.add_roles(membro)
        await member.remove_roles(convidado)

        with self.bot.db_session() as session:
            user = User(ingame_name=user_data['name'], discord_id=str(ctx.author.id), discord_name=str(ctx.author))
            session.add(user)

        auth_chat = self.bot.setting.chat.get('auth')
        auth_chat: discord.TextChannel = atlantis.get_channel(auth_chat)

        await ctx.send(
            f"Autenticação finalizada {ctx.author.mention}, você agora é é um Membro no Discord do Atlantis!\n\n"
            f"***Nota:*** Caso saia do Clã ou troque de nome, iremos notificar a necessidade de refazer o "
            f"processo de Autenticação, caso não o faça em até 7 dias, removeremos o seu cargo "
            f"de Membro."
        )
        await auth_chat.send(
            f"{ctx.author} se autenticou como Membro. (id: {ctx.author.id}, username: {user_data['name']}) "
            f"com os mundos: {', '.join([str(world) for world in worlds_done])}"
        )
        logger_atl.info(f'Autenticação finalizada: {ctx.author} ({user_data}) {settings}')


def setup(bot):
    bot.add_cog(UserAuthentication(bot))