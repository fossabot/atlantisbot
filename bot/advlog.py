import asyncio
import csv
import traceback
import re
import ast
from io import StringIO

import aiohttp
import discord

from .cogs.models import Session, PlayerActivities


async def advlog(client):
    while True:
        async with aiohttp.ClientSession() as cs:
            clan = f"http://services.runescape.com/m=clan-hiscores/members_lite.ws?clanName={client.setting.clan_name}"
            async with cs.get(clan) as r:
                clan_csv = await r.text()
                clan_list = list(csv.reader(StringIO(clan_csv), delimiter=','))
            new_activities = {}
            success = 0
            profile_private = 0
            not_member = 0
            for player in clan_list[1:]:
                player = player[0]
                profile_url = f'https://apps.runescape.com/runemetrics/profile/profile?user={player}&activities=20'
                async with cs.get(profile_url) as r:
                    call = await r.json()
                    if call.get('error') == 'PROFILE_PRIVATE':
                        new_activities[player] = []
                        profile_private += 1
                    elif call.get('error') == 'NOT_A_MEMBER':
                        new_activities[player] = []
                        not_member += 1
                    else:
                        if call.get('activities'):
                            new_activities[player] = call.get('activities')
                            success += 1
            print(f"Finished grabbing adv log data. Success: {success} "
                  f"- Private Profile: {profile_private} "
                  f"- Not a Member: {not_member}")
            session = Session()
            all_activities = session.query(PlayerActivities).all()
            old_activities = {}
            if all_activities:
                for act in all_activities:
                    act_list = ast.literal_eval(act.activities)
                    old_activities[act.name] = act_list

            new_keys = set(new_activities) - set(old_activities)
            difference = {}
            for key, item in new_activities.items():
                if key not in new_keys:
                    diff_items = [act for act in item if act not in old_activities.get(key)]
                    difference[key] = diff_items
            difference.update({k: new_activities[k] for k in new_keys})
            for key, item in new_activities.items():
                old_player = session.query(PlayerActivities).filter_by(name=key).first()
                if old_player:
                    old_player.activities = str(item)
                else:
                    new_player = PlayerActivities(name=key, activities=str(item))
                    session.add(new_player)
                session.commit()
            session.close()
            channel = client.get_channel(client.setting.chat.get('adv_log'))
            banner = f"http://services.runescape.com/m=avatar-rs/l=3/a=869/{client.setting.clan_name}/clanmotif.png"
            for player, activities in difference.items():
                icon_url = f"https://secure.runescape.com/m=avatar-rs/{player.replace(' ', '%20')}/chat.png"
                for activity in activities:
                    text = activity.get('text')
                    details = activity.get('details')
                    try:
                        text_exp = int(re.findall('\d+', text)[0])
                        details_exp = int(re.findall('\d+', text)[0])
                        text = text.replace(str(text_exp), f"{text_exp:,}")
                        details = details.replace(str(details_exp), f"{details_exp:,}")
                    except IndexError:
                        pass
                    embed = discord.Embed(
                        title=text,
                        description=details
                    )
                    embed.set_author(
                        name=player,
                        icon_url=icon_url
                    )
                    embed.set_thumbnail(url=banner)
                    embed.set_footer(text=activity.get('date'))
                    try:
                        # TODO: Remove after db has been built once
                        if '19-Nov-2018' in activity.get('date'):
                            await channel.send(embed=embed)
                    except Exception as e:
                        tb = traceback.format_exc()
                        print(e, tb)
        await asyncio.sleep(180)