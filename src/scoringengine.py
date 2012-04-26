# -*- coding: utf-8 -*-

"""Copyright (C) 2009-2012 Wolfgang Rohdewald <wolfgang@rohdewald.de>

kajongg is free software you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation either version 2 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program if not, write to the Free Software
Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.



Read the user manual for a description of the interface to this scoring engine
"""

from util import logDebug
from meld import Meld, meldKey, Score, meldsContent, Pairs, CONCEALED
from common import Debug

class UsedRule(object):
    """use this in scoring, never change class Rule.
    If the rule has been used for a meld, pass it"""
    def __init__(self, rule, meld=None):
        self.rule = rule
        self.meld = meld

class HandContent(object):
    """represent the hand to be evaluated"""

    # pylint: disable=R0902
    # pylint we need more than 10 instance attributes

    cache = dict()
    misses = 0
    hits = 0

    @staticmethod
    def clearCache():
        """clears the cache with HandContents"""
        if Debug.handCache:
            logDebug('cache size:%d hits:%d misses:%d' % (len(HandContent.cache), HandContent.hits, HandContent.misses))
        HandContent.cache.clear()
        HandContent.hits = 0
        HandContent.misses = 0

    @staticmethod
    def cached(ruleset, string, computedRules=None, robbedTile=None):
        """since a HandContent instance is never changed, we can use a cache"""
        cRuleHash = '&&'.join([rule.name for rule in computedRules]) if computedRules else 'None'
        cacheKey = hash((id(ruleset), string, robbedTile, cRuleHash))
        cache = HandContent.cache
        if cacheKey in cache:
            if cache[cacheKey] is None:
                raise Exception('recursion: HandContent calls itself for same content')
            HandContent.hits += 1
            return cache[cacheKey]
        HandContent.misses += 1
        cache[cacheKey] = None
        result = HandContent(ruleset, string,
            computedRules=computedRules, robbedTile=robbedTile)
        cache[cacheKey] = result
        return result

    def __init__(self, ruleset, string, computedRules=None, robbedTile=None):
        """evaluate string using ruleset. rules are to be applied in any case."""
        # silence pylint. This method is time critical, so do not split it into smaller methods
        # pylint: disable=R0902,R0914,R0912,R0915
        self.ruleset = ruleset
        self.string = string
        if string.count('R') > 1:
            raise Exception('string has more than on R part:%s'%string)
        self.robbedTile = robbedTile
        self.computedRules = computedRules or []
        self.won = False
        self.mayWin = True
        self.ownWind = None
        self.roundWind = None
        tileStrings = []
        mjStrings = []
        haveM = haveL = False
        splits = self.string.split()
        for part in splits:
            partId = part[0]
            if partId in 'Mmx':
                haveM = True
                self.ownWind = part[1]
                self.roundWind = part[2]
                mjStrings.append(part)
                self.won = partId == 'M'
                self.mayWin = partId != 'x'
            elif partId == 'L':
                haveL = True
                if len(part[1:]) > 8:
                    raise Exception('last tile cannot complete a kang:' + self.string)
                mjStrings.append(part)
            else:
                tileStrings.append(part)

        if not haveM:
            raise Exception('HandContent got string without mMx: %s', self.string)
        if not haveL:
            mjStrings.append('Lxx')
        self.tiles = ' '.join(tileStrings)
        self.mjStr = ' '.join(mjStrings)
        self.lastMeld = self.lastTile = self.lastSource = None
        self.announcements = ''
        self.hiddenMelds = []
        self.declaredMelds = []
        self.melds = []
        self.fsMelds = []
        self.invalidMelds = []
        self.__separateMelds()
        self.tileNames = []
        self.dragonMelds = [x for x in self.melds if x.pairs[0][0] in 'dD']
        self.windMelds = [x for x in self.melds if x.pairs[0][0] in 'wW']
        for meld in self.melds:
            self.tileNames.extend(meld.pairs)
        self.hiddenMelds = sorted(self.hiddenMelds, key=meldKey)
        self.suits = set(x[0].lower() for x in self.tileNames)
        self.values = ''.join(x[1] for x in self.tileNames)
        self.__setLastMeldAndTile()
        assert self.lastTile == 'xx' or self.lastTile in self.tileNames, 'lastTile %s is not in tiles %s' % (
            self.lastTile, ' '.join(self.tileNames))
        if self.lastTile != 'xx' and self.lastSource == 'k':
            assert self.tileNames.count(self.lastTile.lower()) + \
                self.tileNames.count(self.lastTile.capitalize()) == 1, \
                'Robbing kong: I cannot have lastTile %s more than once in %s' % (
                    self.lastTile, ' '.join(self.tileNames))

        if self.invalidMelds:
            raise Exception('has invalid melds: ' + ','.join(meld.joined for meld in self.invalidMelds))

        self.sortedMeldsContent = meldsContent(self.melds)
        if self.fsMelds:
            self.sortedMeldsContent += ' ' + meldsContent(self.fsMelds)
        self.fsMeldNames = [x.pairs[0] for x in self.fsMelds]

        self.usedRules = []
        self.score = None
        oldWon = self.won
        self.applyRules()
        if self.won != oldWon:
            # if not won after all, this might be a long hand.
            # So we might even have to unapply meld rules and
            # bonus points. Instead just recompute all again.
            # This should only happen with scoring manual games
            # and with scoringtest - normally kajongg would not
            # let you declare an invalid mah jongg
            self.applyRules()

    def applyRules(self):
        """find out which rules apply, collect in self.usedRules.
        This may change self.won"""
        self.usedRules = list([UsedRule(rule) for rule in self.computedRules])
        if self.hasExclusiveRules():
            return
        self.applyMeldRules()

        self.usedRules.extend(list([UsedRule(rule) for rule in self.matchingRules(
            self.ruleset.handRules)]))
        if self.hasExclusiveRules():
            return
        self.score = self.__totalScore()
        if self.won:
            # first we only assume having a winning hand. Because
            # some doubles needed for reaching minimum doubles might
            # come from the winning rules, we must apply them before
            # checking if we really have a valid winning hand.
            prevUsedRules = self.usedRules[:]
            winnerRules = self.matchingWinnerRules()
            self.usedRules.extend(winnerRules)
            self.score = self.__totalScore()
            matchingMJRules = self.maybeMahjongg()
            if not matchingMJRules:
                # not a winning hand after all. Unapply the
                # winner rules again.
                self.won = False
                self.usedRules = prevUsedRules
                self.score = self.__totalScore()
                return
            self.usedRules.append(UsedRule(matchingMJRules[0]))
            if self.hasExclusiveRules():
                return
            self.score = self.__totalScore()

    def matchingWinnerRules(self):
        """returns a list of matching winner rules"""
        matching = self.matchingRules(self.ruleset.winnerRules)
        for rule in matching:
            if (self.ruleset.limit and rule.score.limits >= 1) or 'absolute' in rule.options:
                return [UsedRule(rule)]
        return list(UsedRule(x) for x in matching)

    def hasExclusiveRules(self):
        """if we have one, remove all others"""
        exclusive = list(x for x in self.usedRules if 'absolute' in x.rule.options)
        if exclusive:
            self.usedRules = exclusive
            self.score = self.__totalScore()
            self.won = self.won and self.maybeMahjongg()
        return bool(exclusive)

    def __setLastMeldAndTile(self):
        """returns Meld and Tile or None for both"""
        parts = self.mjStr.split()
        for part in parts:
            if part[0] == 'L':
                part = part[1:]
                if len(part) > 2:
                    self.lastMeld = Meld(part[2:])
                self.lastTile = part[:2]
            elif part[0] == 'M':
                if len(part) > 3:
                    self.lastSource = part[3]
                    if len(part) > 4:
                        self.announcements = part[4:]
        if self.lastTile and not self.lastMeld:
            self.lastMeld = self.computeLastMeld(self.lastTile)

    def __sub__(self, tiles):
        """returns a copy of self minus tiles. Case of tiles (hidden
        or exposed) is ignored. If the tile is not hidden
        but found in an exposed meld, this meld will be hidden with
        the tile removed from it. Exposed melds of length<3 will also
        be hidden."""
        # pylint: disable=R0912
        # pylint says too many branches
        if not isinstance(tiles, list):
            tiles = list([tiles])
        hidden = 'R' + ''.join(x.joined for x in self.hiddenMelds)
        # exposed is a deep copy of declaredMelds. If lastMeld is given, it
        # must be first in the list.
        exposed = (Meld(x) for x in self.declaredMelds)
        if self.lastMeld:
            exposed = sorted(exposed, key=lambda x: (x.pairs != self.lastMeld.pairs, meldKey(x)))
        else:
            exposed = sorted(exposed, key=meldKey)
        for tile in tiles:
            assert isinstance(tile, str) and len(tile) == 2, 'HandContent.__sub__:%s' % tiles
            if tile.capitalize() in hidden:
                hidden = hidden.replace(tile.capitalize(), '', 1)
            else:
                for idx, meld in enumerate(exposed):
                    if tile.lower() in meld.pairs:
                        del meld.pairs[meld.pairs.index(tile.lower())]
                        del exposed[idx]
                        meld.conceal()
                        hidden += meld.joined
                        break
        for idx, meld in enumerate(exposed):
            if len(meld.pairs) < 3:
                del exposed[idx]
                meld.conceal()
                hidden += meld.joined
        mjStr = self.mjStr
        if self.lastTile in tiles:
            parts = mjStr.split()
            for idx, part in enumerate(parts):
                if part[0] == 'L':
                    parts[idx] = 'Lxx'
                if part[0] == 'M':
                    parts[idx] = 'm' + part[1:]
                    if len(part) > 3 and part[3] == 'k':
                        parts[idx] = parts[idx][:3]
            mjStr = ' '.join(parts)
        newString = ' '.join([hidden, meldsContent(exposed), mjStr])
        return HandContent.cached(self.ruleset, newString, self.computedRules)

    def ruleMayApply(self, rule):
        """returns True if rule applies to this hand"""
        return rule.appliesToHand(self)

    def manualRuleMayApply(self, rule):
        """returns True if rule has selectable() and applies to this hand"""
        return rule.selectable(self) or self.ruleMayApply(rule) # needed for activated rules

    def handLenOffset(self):
        """return <0 for short hand, 0 for correct calling hand, >0 for long hand
        if there are no kongs, 13 tiles will return 0"""
        tileCount = sum(len(meld) for meld in self.melds)
        kongCount = self.countMelds(Meld.isKong)
        return tileCount - kongCount - 13

    def callingHands(self, wanted=1, excludeTile=None):
        """the hand is calling if it only needs one tile for mah jongg.
        Returns up to 'wanted' hands which would only need one tile.
        Does NOT check if they are really available by looking at what
        has already been discarded!
        """
        result = []
        string = self.string
        if ' x' in string or self.handLenOffset():
            return result
        for rule in self.ruleset.mjRules:
            # sort only for reproducibility
            if not hasattr(rule, 'winningTileCandidates'):
                raise Exception('rule %s, code=%s has no winningTileCandidates' % (
                    rule.name, rule.function))
            candidates = sorted(x.capitalize() for x in rule.winningTileCandidates(self))
            for tileName in candidates:
                if excludeTile and tileName == excludeTile.capitalize():
                    continue
                thisOne = self.addTile(string, tileName).replace(' m', ' M')
                hand = HandContent.cached(self.ruleset, thisOne)
                if hand.maybeMahjongg():
                    result.append(hand)
                    if len(result) == wanted:
                        break
            if len(result) == wanted:
                break
        return result

    def maybeMahjongg(self):
        """check if this is a mah jongg hand.
        Return a sorted list of matching MJ rules, highest
        total first"""
        if not self.mayWin:
            return []
        if self.handLenOffset() != 1:
            return []
        matchingMJRules = [x for x in self.ruleset.mjRules if self.ruleMayApply(x)]
        if self.robbedTile and self.robbedTile.lower() != self.robbedTile:
            # Millington 58: robbing hidden kong is only allowed for 13 orphans
            matchingMJRules = [x for x in matchingMJRules if 'mayrobhiddenkong' in x.options]
        return sorted(matchingMJRules, key=lambda x: -x.score.total())

    def computeLastMeld(self, lastTile):
        """returns the best last meld for lastTile"""
        if lastTile == 'xx':
            return
        if lastTile[0].isupper():
            checkMelds = self.hiddenMelds
        else:
            checkMelds = self.declaredMelds
        checkMelds = [x for x in checkMelds if len(x) < 4] # exclude kongs
        lastMelds = [x for x in checkMelds if lastTile in x.pairs]
        if not lastMelds:
            # lastTile was Xy or already discarded again
            self.lastTile = 'xx'
            return
        if len(lastMelds) > 1:
            for meld in lastMelds:
                if meld.isPair():       # completing pairs gives more points.
                    return meld
            for meld in lastMelds:
                if meld.isChow():       # if both chow and pung wins the game, call
                    return meld         # chow because hidden pung gives more points
        return lastMelds[0]             # default: the first possible last meld

    def splitRegex(self, rest):
        """split self.tiles into melds as good as possible"""
        melds = []
        for rule in self.ruleset.splitRules:
            splits = rule.apply(rest)
            while len(splits) >1:
                for split in splits[:-1]:
                    melds.append(Meld(split))
                rest = splits[-1]
                splits = rule.apply(rest)
            if len(splits) == 0:
                break
        if len(splits) == 1 :
            assert Meld(splits[0]).isValid()   # or the splitRules are wrong
        return melds

    def genVariants(self, original0, maxPairs=1):
        """generates all possible meld variants out of original
        where original is a list of tile values like ['1','1','2']"""
        color = original0[0][0]
        original = [x[1] for x in original0]
        def recurse(cVariants, foundMelds, rest):
            """build the variants recursively"""
            values = set(rest)
            melds = []
            for value in values:
                intValue = int(value)
                if rest.count(value) == 3:
                    melds.append([value] * 3)
                elif rest.count(value) == 2:
                    melds.append([value] * 2)
                if rest.count(str(intValue + 1)) and rest.count(str(intValue + 2)):
                    melds.append([value, str(intValue+1), str(intValue+2)])
            pairsFound = sum(len(x) == 2 for x in foundMelds)
            for meld in (m for m in melds if len(m) !=2 or pairsFound < maxPairs):
                restCopy = rest[:]
                for value in meld:
                    restCopy.remove(value)
                newMelds = foundMelds[:]
                newMelds.append(meld)
                if restCopy:
                    recurse(cVariants, newMelds, restCopy)
                else:
                    for idx, newMeld in enumerate(newMelds):
                        newMelds[idx] = ''.join(color+x for x in newMeld)
                    cVariants.append(' '.join(sorted(newMelds )))
        cVariants = []
        recurse(cVariants, [], original)
        gVariants = []
        for cVariant in set(cVariants):
            melds = [Meld(x) for x in cVariant.split()]
            gVariants.append(melds)
        if not gVariants:
            gVariants.append(self.splitRegex(''.join(original0))) # fallback: nothing useful found
        return gVariants

    def split(self, rest):
        """work hard to always return the variant with the highest Mah Jongg value."""
        pairs = Meld(rest).pairs
        if 'Xy' in pairs:
            # hidden tiles of other players:
            return self.splitRegex(rest)
        _ = [pair for pair in pairs if pair[0] in 'DWdw']
        honourResult = self.splitRegex(''.join(_)) # easy since they cannot have a chow
        splitVariants = {}
        for color in 'SBC':
            colorPairs = [pair for pair in pairs if pair[0] == color]
            if not colorPairs:
                splitVariants[color] = [None]
                continue
            splitVariants[color] = self.genVariants(colorPairs)
        bestHand = None
        bestVariant = None
        for combination in ((s, b, c)
                for s in splitVariants['S']
                for b in splitVariants['B']
                for c in splitVariants['C']):
            variantMelds = honourResult[:] + sum((x for x in combination if x is not None), [])
            melds = self.melds[:] + variantMelds
            melds.extend(self.fsMelds)
            _ = ' '.join(x.joined for x in melds) + ' ' + self.mjStr
            hand = HandContent.cached(self.ruleset, _,
                computedRules=self.computedRules)
            if not bestHand or hand.total() > bestHand.total():
                bestHand = hand
                bestVariant = variantMelds
        return bestVariant

    def countMelds(self, key):
        """count melds having key"""
        result = 0
        if isinstance(key, str):
            for meld in self.melds:
                if meld.tileType() in key:
                    result += 1
        else:
            for meld in self.melds:
                if key(meld):
                    result += 1
        return result

    def matchingRules(self, rules):
        """return all matching rules for this hand"""
        return list(rule for rule in rules if rule.appliesToHand(self))

    def applyMeldRules(self):
        """apply all rules for single melds"""
        for rule in self.ruleset.meldRules:
            for meld in self.melds + self.fsMelds:
                if rule.appliesToMeld(self, meld):
                    self.usedRules.append(UsedRule(rule, meld))

    def __totalScore(self):
        """use all used rules to compute the score"""
        return sum([x.rule.score for x in self.usedRules], Score()) if self.usedRules else Score()

    def total(self):
        """total points of hand"""
        return self.score.total()

    def __separateMelds(self):
        """build a meld list from the hand string"""
        # no matter how the tiles are grouped make a single
        # meld for every bonus tile
        boni = []
        # we need to remove spaces from the hand string first
        # for building only pairs with length 2
        for pair in Pairs(self.tiles.replace(' ', '').replace('R', '')):
            if pair[0] in 'fy':
                boni.append(pair)
                self.tiles = self.tiles.replace(pair, '', 1)
        splits = self.tiles.split()
        splits.extend(boni)
        rest = ''
        for split in splits:
            if split[0] == 'R':
                rest = split[1:]
            else:
                self.melds.append(Meld(split))
        if rest:
            rest = ''.join(sorted([rest[x:x+2] for x in range(0, len(rest), 2)]))
            self.melds.extend(self.split(rest))
        self.melds = sorted(self.melds, key=meldKey)
        self.__categorizeMelds()

    @staticmethod
    def addTile(string, tileName):
        """string is the encoded hand. Add tileName in the right place
        and return the new string. Use this only for a hand getting
        a claimed or discarded tile."""
        if not tileName:
            return string
        parts = string.split()
        mPart = ''
        rPart = 'R%s' % tileName
        unchanged = []
        for part in parts:
            if part[0] in 'SBCDW':
                rPart += part
            elif part[0] == 'R':
                rPart += part[1:]
            elif part[0].lower() == 'm':
                mPart = part
            elif part[0] == 'L':
                pass
            else:
                unchanged.append(part)
        # combine all parts about hidden tiles plus the new one to one part
        # because something like DrDrS8S9 plus S7 will have to be reordered
        # anyway
        parts = unchanged
        parts.append(rPart)
        parts.append('L%s' % tileName)
        parts.append(mPart.capitalize())
        return ' '.join(parts)

    def __categorizeMelds(self):
        """categorize: boni, hidden, declared, invalid"""
        self.fsMelds = []
        self.invalidMelds = []
        self.hiddenMelds = []
        self.declaredMelds = []
        for meld in self.melds:
            if not meld.isValid():
                self.invalidMelds.append(meld)
            elif meld.tileType() in 'fy':
                self.fsMelds.append(meld)
            elif meld.state == CONCEALED and not meld.isKong():
                self.hiddenMelds.append(meld)
            else:
                self.declaredMelds.append(meld)
        for meld in self.fsMelds:
            self.melds.remove(meld)

    def explain(self):
        """explain what rules were used for this hand"""
        result = [x.rule.explain() for x in self.usedRules
            if x.rule.score.points]
        result.extend([x.rule.explain() for x in self.usedRules
            if x.rule.score.doubles])
        result.extend([x.rule.explain() for x in self.usedRules
            if not x.rule.score.points and not x.rule.score.doubles])
        if any(x.rule.debug for x in self.usedRules):
            result.append(str(self))
        return result

    def __str__(self):
        """hand as a string"""
        return u' '.join([self.sortedMeldsContent, self.mjStr])
