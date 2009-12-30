#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Copyright (C) 2008,2009 Wolfgang Rohdewald <wolfgang@rohdewald.de>

kmj is free software you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation either version 2 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program if not, write to the Free Software
Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.
"""

import sys, datetime, syslog, string
from random import randrange, shuffle

from PyQt4.QtCore import Qt
from PyQt4.QtGui import QBrush, QColor

from util import logMessage,  logException, m18n, WINDS

from query import Query
from scoringengine import Ruleset
from tileset import Elements
from tile import Tile
from scoringengine import Pairs, Meld, HandContent

class Players(list):
    """a list of players where the player can also be indexed by wind"""

    allNames = {}
    allIds = {}

    def __init__(self, players=None):
        list.__init__(self)
        if players:
            self.extend(players)

    def __getitem__(self, index):
        """allow access by idx or by wind"""
        if isinstance(index, (bytes, str)) and len(index) == 1:
            # bytes for Python 2.6, str for 3.0
            for player in self:
                if player.wind == index:
                    return player
            logException(Exception("no player has wind %s" % index))
        return list.__getitem__(self, index)

    def __str__(self):
        return ', '.join(list('%s: %s' % (x.name, x.wind) for x in self))

    def byId(self, playerid):
        """lookup the player by id"""
        for player in self:
            if player.nameid == playerid:
                return player
        logException(Exception("no player has id %d" % playerid))

    def byName(self, playerName):
        """lookup the player by name"""
        for player in self:
            if player.name == playerName:
                return player
        logException(Exception("no player has name %s" % playerName))

    @staticmethod
    def load():
        """load all defined players into self.allIds and self.allNames"""
        query = Query("select id,host,name from player")
        if not query.success:
            sys.exit(1)
        Players.allIds = {}
        Players.allNames = {}
        for record in query.data:
            (nameid, host,  name) = record
            Players.allIds[(host, name)] = nameid
            Players.allNames[nameid] = (host, name)

    @staticmethod
    def createIfUnknown(host, name):
        if (host, name) not in Players.allNames.values():
            Query("insert into player(host,name) values('%s','%s')" % (host, name))
            Players.load()
        assert (host, name) in Players.allNames.values()

class Player(object):
    """all player related data without GUI stuff"""
    def __init__(self, game, handContent=None):
        self.game = game
        self.handContent = handContent
        self.__balance = 0
        self.__payment = 0
        self.name = ''
        self.wind = WINDS[0]
        self.total = 0
        self.concealedTiles = []
        self.exposedMelds = []
        self.remote = None # only for server
        self.field = None # this tells us if it is a VisiblePlayer (has a field) or not

    @apply
    def nameid():
        """the name id of this player"""
        def fget(self):
            return Players.allIds[(self.game.host,  self.name)]
        return property(**locals())

    @apply
    def balance():
        """the balance of this player"""
        def fget(self):
            return self.__balance
        def fset(self, balance):
            assert balance == 0
            self.__balance = 0
            self.__payment = 0
        return property(**locals())

    def getsPayment(self, payment):
        """make a payment to this player"""
        self.__balance += payment
        self.__payment += payment

    @apply
    def payment():
        """the payments for the current hand"""
        def fget(self):
            return self.__payment
        def fset(self, payment):
            assert payment == 0
            self.__payment = 0
        return property(**locals())

    def __repr__(self):
        return '%s %s' % (self.name,  self.wind)

    def addTile(self, tileName):
        """add to my concealed tiles"""
        self.concealedTiles.append(tileName)

    def removeTile(self, tileName):
        """remove from my concealed tiles"""
        self.concealedTiles.remove(tileName)

    def hasConcealedTiles(self, tileNames):
        """do I have those concealed tiles?"""
        concealedTiles = self.concealedTiles[:]
        for tile in tileNames:
            if tile not in concealedTiles:
                return False
            concealedTiles.remove(tile)
        return True

    def hasExposedPungOf(self, tileName):
        for meld in self.exposedMelds:
            if meld.content == tileName.lower() * 3:
                return True
        return False

    def makeTilesKnown(self, tileNames):
        """another player exposes something"""
        if not isinstance(tileNames, list):
            tileNames = [tileNames]
        for tileName in tileNames:
            if tileName[0].isupper() or tileName[0] in 'fy':
                # VisiblePlayer.addtile would update HandBoard
                # but we do not want that now
                Player.addTile(self, tileName)
                Player.removeTile(self,'XY')

    def exposeMeld(self, meldTiles, claimed=True):
        """exposes a meld with meldTiles: removes them from concealedTiles,
        adds the meld to exposedMelds
        lastTile is the tile just added to the player. If we declare
        a kong we already had, lastTile is None.
        lastTile is not included in meldTiles.
        If lastTile is a claimed tile, it is already exposed"""
        game = self.game
        game.activePlayer = self
        if len(meldTiles) == 4 and meldTiles[0].islower():
            tile0 = meldTiles[0].lower()
            # we are adding a 4th tile to an exposed pung
            self.exposedMelds = [meld for meld in self.exposedMelds if meld.content != tile0 * 3]
            self.exposedMelds.append(Meld(tile0 * 4))
            self.concealedTiles.remove(meldTiles[3])
        else:
            for meldTile in meldTiles:
                assert not meldTile.islower(), meldTiles
                self.concealedTiles.remove(meldTile)
            if len(meldTiles) < 4:
                meldTiles = [x.lower() for x in meldTiles]
            else:
                meldTiles = meldTiles[:]  # we must not change the passed list!
                if claimed:
                    lower = [0, 1, 2]
                else: # concealed kong
                    lower = [0, 3]
                for idx in range(4):
                    if idx in lower:
                        meldTiles[idx] = meldTiles[idx].lower()
                    else:
                        meldTiles[idx] = meldTiles[idx][0].upper() + meldTiles[idx][1]
            self.exposedMelds.append(Meld(meldTiles))

    def popupMsg(self, msg):
        pass

    def hidePopup(self):
        pass

    def syncHandBoard(self):
        pass

    def hand(self):
        melds = [''.join(self.concealedTiles)]
        melds.extend(x.content for x in self.exposedMelds)
        return HandContent.cached(self.game.ruleset, ' '.join(melds))

    def offsetTiles(self, tileName, offsets):
        chow2 = Tile.chiNext(tileName, offsets[0])
        chow3 = Tile.chiNext(tileName, offsets[1])
        return [chow2, chow3]

    def possibleChows(self, tileName):
        """returns a unique list of lists with possible chow combinations"""
        try:
            value = int(tileName[1])
        except ValueError:
            return []
        chows = []
        for offsets in [(1, 2), (-2, -1), (-1, 1)]:
            if value + offsets[0] >= 1 and value + offsets[1] <= 9:
                chow = self.offsetTiles(tileName, offsets)
                if self.hasConcealedTiles(chow):
                    chow.append(tileName)
                    if chow not in chows:
                        chows.append(sorted(chow))
        return chows


class Game(object):
    """the game without GUI"""
    def __init__(self, host, names, ruleset, gameid=None, field=None):
        """a new game instance. May be shown on a field, comes from database if gameid is set"""
        if not host:
            host = ''
        self.host = host
        self.rotated = 0
        self.field = field
        self.ruleset = None
        self.winner = None
        self.roundsFinished = 0
        self.gameid = gameid
        self.handctr = 0
        self.wallTiles = None
        self.diceSum = None
        self.lastDiscard = None
        self.client = None # default: no network game
        # shift rules taken from the OEMC 2005 rules
        # 2nd round: S and W shift, E and N shift
        self.shiftRules = 'SWEN,SE,WE'
        for name in names:
            Players.createIfUnknown(host, name)
        if field:
            self.players = field.genPlayers(self)
        else:
            self.players = Players([Player(self) for idx in range(4)])
        for idx, player in enumerate(self.players):
            player.name = names[idx]
            player.wind = WINDS[idx]
        self.__useRuleset(ruleset)
        if not self.gameid:
            self.gameid = self.__newGameId()

    def losers(self):
        """the 3 or 4 losers: All players without the winner"""
        return list([x for x in self.players if x is not self.winner])

    @staticmethod
    def __windOrder(player):
        """cmp function for __exchangeSeats"""
        return 'ESWN'.index(player.wind)

    def __exchangeSeats(self):
        """execute seat exchanges according to the rules"""
        windPairs = self.shiftRules.split(',')[self.roundsFinished-1]
        while len(windPairs):
            windPair = windPairs[0:2]
            windPairs = windPairs[2:]
            swappers = list(self.players[windPair[x]] for x in (0, 1))
            if self.field is None or self.field.askSwap(swappers):
                swappers[0].wind,  swappers[1].wind = swappers[1].wind,  swappers[0].wind
        self.players.sort(key=Game.__windOrder)

    def __newGameId(self):
        """write a new entry in the game table with the selected players
        and returns the game id of that new entry"""
        starttime = datetime.datetime.now().replace(microsecond=0).isoformat()
        # first insert and then find out which game id we just generated. Clumsy and racy.
        return Query([
            "insert into game(starttime,ruleset,p0,p1,p2,p3) values('%s', %d, %s)" % \
                (starttime, self.ruleset.rulesetId, ','.join(str(p.nameid) for p in self.players)),
            "update usedruleset set lastused='%s' where id=%d" %\
                (starttime, self.ruleset.rulesetId),
            "update ruleset set lastused='%s' where hash='%s'" %\
                (starttime, self.ruleset.hash),
            "select id from game where starttime = '%s'" % \
                starttime]).data[0][0]

    def __useRuleset(self,  ruleset):
        """use a copy of ruleset for this game, reusing an existing copy"""
        self.ruleset = ruleset
        self.ruleset.load()
        query = Query('select id from usedruleset where hash="%s"' % \
              (self.ruleset.hash))
        if query.data:
            # reuse that usedruleset
            self.ruleset.rulesetId = query.data[0][0]
        else:
            # generate a new usedruleset
            self.ruleset.rulesetId = self.ruleset.newId(used=True)
            self.ruleset.save()

    def saveHand(self):
        """save hand to data base, update score table and balance in status line"""
        self.__payHand()
        self.__saveScores()
        self.rotate()

    def __saveScores(self):
        """save computed values to data base, update score table and balance in status line"""
        scoretime = datetime.datetime.now().replace(microsecond=0).isoformat()
        cmdList = []
        for player in self.players:
            if player.handContent:
                manualrules = '||'.join(x.name for x, meld in player.handContent.usedRules)
            else:
                manualrules = m18n('Score computed manually')
            cmdList.append("INSERT INTO SCORE "
            "(game,hand,data,manualrules,player,scoretime,won,prevailing,wind,points,payments, balance,rotated) "
            "VALUES(%d,%d,'%s','%s',%d,'%s',%d,'%s','%s',%d,%d,%d,%d)" % \
            (self.gameid, self.handctr, player.handContent.string, manualrules, player.nameid,
                scoretime, int(player == self.winner),
            WINDS[self.roundsFinished], player.wind, player.total,
            player.payment, player.balance, self.rotated))
        Query(cmdList)

    def savePenalty(self, player, offense, amount):
        """save computed values to data base, update score table and balance in status line"""
        scoretime = datetime.datetime.now().replace(microsecond=0).isoformat()
        cmdList = []
        cmdList.append("INSERT INTO SCORE "
            "(game,hand,data,manualrules,player,scoretime,won,prevailing,wind,points,payments, balance,rotated) "
            "VALUES(%d,%d,'%s','%s',%d,'%s',%d,'%s','%s',%d,%d,%d,%d)" % \
            (self.gameid, self.handctr, player.handContent.string, offense.name, player.nameid,
                scoretime, int(player == self.winner),
            WINDS[self.roundsFinished], player.wind, 0,
            amount, player.balance, self.rotated))
        Query(cmdList)
        if self.field:
            self.field.showBalance()

    def rotate(self):
        """rotate winds, exchange seats. If finished, update database"""
        self.handctr += 1
        if self.winner and self.winner.wind != 'E':
            self.rotated += 1
            if self.rotated == 4:
                if not self.finished():
                    self.roundsFinished += 1
                self.rotated = 0
            if self.finished():
                endtime = datetime.datetime.now().replace(microsecond=0).isoformat()
                Query('UPDATE game set endtime = "%s" where id = %d' % \
                      (endtime, self.gameid))
            else:
                winds = [player.wind for player in self.players]
                winds = winds[3:] + winds[0:3]
                for idx,  newWind in enumerate(winds):
                    self.players[idx].wind = newWind
                if 0 < self.roundsFinished < 4 and self.rotated == 0:
                    self.__exchangeSeats()

    @staticmethod
    def load(gameid, field=None):
        """load game data by game id and return a new Game instance"""
        qGame = Query("select p0, p1, p2, p3, ruleset from game where id = %d" % gameid)
        if not qGame.data:
            return None
        rulesetId = qGame.data[0][4] or 1
        ruleset = Ruleset(rulesetId, used=True)
        Players.load() # we want to make sure we have the current definitions
        hosts = []
        names = []
        for idx in range(4):
            nameid = qGame.data[0][idx]
            try:
                (host, name) = Players.allNames[nameid]
            except KeyError:
                name = m18n('Player %1 not known', nameid)
            hosts.append(host)
            names.append(name)
        if len(set(hosts)) != 1:
            logException('Game %d has players from different hosts' % gameid)
        game = Game(hosts[0], names, ruleset, gameid=gameid, field=field)

        qLastHand = Query("select hand,rotated from score where game=%d and hand="
            "(select max(hand) from score where game=%d)" % (gameid, gameid))
        if qLastHand.data:
            (game.handctr, game.rotated) = qLastHand.data[0]

        qScores = Query("select player, wind, balance, won, prevailing from score "
            "where game=%d and hand=%d" % (gameid, game.handctr))
        for record in qScores.data:
            playerid = record[0]
            wind = str(record[1])
            player = game.players.byId(playerid)
            if not player:
                logMessage(
                'game %d data inconsistent: player %d missing in game table' % \
                    (gameid, playerid), syslog.LOG_ERR)
            else:
                player.getsPayment(record[2])
                player.wind = wind
            if record[3]:
                game.winner = player
            prevailing = record[4]
        game.roundsFinished = WINDS.index(prevailing)
        game.rotate()
        return game

    def finished(self):
        """The game is over after 4 completed rounds"""
        return self.roundsFinished == 4

    def __payHand(self):
        """pay the scores"""
        winner = self.winner
        for player in self.players:
            if player.handContent.hasAction('payforall'):
                score = winner.total
                if winner.wind == 'E':
                    score = score * 6
                else:
                    score = score * 4
                player.getsPayment(-score)
                winner.getsPayment(score)
                return

        for idx1, player1 in enumerate(self.players):
            for idx2, player2 in enumerate(self.players):
                if idx1 != idx2:
                    if player1.wind == 'E' or player2.wind == 'E':
                        efactor = 2
                    else:
                        efactor = 1
                    if player2 != winner:
                        player1.getsPayment(player1.total * efactor)
                    if player1 != winner:
                        player1.getsPayment(-player2.total * efactor)

    def checkInvariants(self):
        result = True
        for player in self.players:
            tiles = [x for x in player.concealedTiles if x[0] not in 'fy']
            if len(tiles) % 3 != 1:
                result = False
                print player, 'ERROR: has wrong number of concealed tiles:', \
                    len(tiles), tiles
        return result

class RemoteGame(Game):
    """this game is played using the computer"""

    def __init__(self, host, names, ruleset, gameid=None, field=None):
        """a new game instance. May be shown on a field, comes from database if gameid is set"""
        Game.__init__(self, host, names, ruleset, gameid, field)
        self.__activePlayer = None
        self.prevActivePlayer = None
        self.__myself = None
        self.defaultNameBrush = None

    @apply
    def myself():
        """I am player"""
        def fget(self):
            return self.__myself
        def fset(self, myself):
            if self.__myself != myself:
                self.__myself = myself
        return property(**locals())

    @apply
    def activePlayer():
        """the turn is on this player"""
        def fget(self):
            return self.__activePlayer
        def fset(self, player):
            if self.__activePlayer != player:
                self.prevActivePlayer = self.__activePlayer
                self.__activePlayer = player
                if self.field: # mark the name of the active player in blue
                    for idx, wall in enumerate(self.field.walls):
                        if not self.defaultNameBrush:
                            self.defaultNameBrush = wall.nameLabel.brush()
                        if self.players[idx] == self.activePlayer:
                            brush = QBrush(QColor(Qt.blue))
                        else:
                            brush = self.defaultNameBrush
                        wall.nameLabel.setBrush(brush)
        return property(**locals())

    def IAmNext(self):
        return self.myself == self.nextPlayer()

    def nextPlayer(self, current=None):
        """returns the player after current or after activePlayer"""
        if not current:
            current = self.activePlayer
        pIdx = self.players.index(current)
        return self.players[(pIdx + 1) % 4]

    def nextTurn(self):
        """move activePlayer"""
        self.activePlayer = self.nextPlayer()

    def deal(self):
        """every player gets 13 tiles (including east)"""
        tiles = [Tile(x) for x in Elements.all()]
        self.wallTiles = [tile.upper() for tile in tiles]
        shuffle(self.wallTiles)
        self.diceSum = randrange(1, 7) + randrange(1, 7)
        for player in self.players:
            while sum(x[0] not in'fy' for x in player.concealedTiles) != 13:
                self.dealTile(player)

    def dealTile(self, player=None):
        """deal one tile to player"""
        # TODO: check for empty wall
        assert self.client is None #to be done only by the server
        if not player:
            player = self.activePlayer
        tile = self.wallTiles[0]
        self.wallTiles = self.wallTiles[1:]
        player.addTile(tile)
        return tile

    def setTiles(self, player, tiles):
        """when starting the hand. tiles is one string"""
        for tile in tiles:
            player.addTile(tile)
        if self.field:
            self.field.walls.removeTiles(len(tiles))

    def showTiles(self, player, tiles):
        """when ending the hand. tiles is one string"""
        assert player != self.myself, '%s %s' % (player, self.myself)
        xyTiles = [x for x in player.concealedTiles if x[0] not in 'fy']
        assert len(tiles) == len(xyTiles), '%s %s' % (tiles, xyTiles)
        for tile in tiles:
            Player.removeTile(player,'XY') # without syncing handBoard
            Player.addTile(player, tile)
        player.syncHandBoard()
        if self.field:
            self.field.walls.removeTiles(len(tiles))

    def pickedTile(self, player, tile, deadEnd):
        """got a tile from wall"""
        self.activePlayer = player
        player.addTile(tile)
        if self.field:
            self.field.walls.removeTiles(1, deadEnd)

    def placeMyselfAtBottom(self):
        """rotate the players until name is at bottom and return number of rotations done"""
        players = self.players
        rotations = 0
        myName = self.myself.name
        while players[0].name != myName:
            rotations += 1
            name0, wind0 = players[0].name, players[0].wind
            for idx in range(4, 0, -1):
                this, prev = players[idx % 4], players[idx - 1]
                this.name, this.wind = prev.name, prev.wind
            players[1].name,  players[1].wind = name0, wind0
        self.myself = players[0]
        return rotations

    def showField(self):
        """show game in field"""
        if self.field:
            rotations = self.placeMyselfAtBottom()
            field = self.field
            for tableList in field.tableLists:
                tableList.hide()
            field.tableLists = []
            field.game = self
            field.walls.build(rotations, self.diceSum)

    def hasDiscarded(self, player, tileName):
        """discards a tile from a player board"""
        self.lastDiscard = tileName
        if player != self.activePlayer:
            raise Exception('Player %s discards but %s is active' % (player, self.activePlayer))
        if self.field:
            self.field.discardBoard.addTile(tileName)
        if self.myself and player != self.myself:
            # we are human and server tells us another player discarded a tile. In our
            # game instance, tiles in handBoards of other players are unknown
            tileName = 'XY'
        if not tileName in player.concealedTiles:
            raise Exception('I am %s. Player %s is told to show discard of tile %s but does not have it' % \
                           (self.myself.name if self.myself else 'None', player.name, tileName))
        player.removeTile(tileName)
        self.checkInvariants()
